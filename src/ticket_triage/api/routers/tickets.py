"""Ticket intake and triage.

Stage 2 scope: classify, look the order up, evaluate the policy, persist everything.
Reply generation and the auto-vs-escalate decision land in Stage 3.
"""

import logging
from typing import Annotated

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status

from ...db.repositories.sqlalchemy_impl import (
    SqlAlchemyOrderRepository,
    SqlAlchemyTicketRepository,
)
from ...db.session import session_scope
from ...domain.enums import TicketStatus
from ...llm.classifier import Classifier
from ...policy.engine import PolicyEngine
from ..deps import get_classifier, get_policy_engine
from ..schemas import (
    ClassificationOut,
    CreateTicketRequest,
    OrderOut,
    PolicyOut,
    TriageResponse,
    UsageOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("", response_model=TriageResponse, status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: CreateTicketRequest,
    classifier: Annotated[Classifier, Depends(get_classifier)],
    policy_engine: Annotated[PolicyEngine, Depends(get_policy_engine)],
) -> TriageResponse:
    """Accept a customer message and run it through the triage pipeline."""

    # The ticket is stored before anything can fail, so a model outage never loses
    # a customer message - it leaves a row in state `new` to retry.
    with session_scope() as session:
        ticket_id = SqlAlchemyTicketRepository(session).create(
            raw_text=payload.text, channel=payload.channel
        )

    try:
        classification, usage = classifier.classify(payload.text)
    except anthropic.APIStatusError as exc:
        _mark_failed(ticket_id)
        logger.exception("Classification failed for ticket %s", ticket_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Klasyfikacja nie powiodła się: {exc.message}",
        ) from exc
    except anthropic.APIConnectionError as exc:
        _mark_failed(ticket_id)
        logger.exception("Cannot reach the Anthropic API for ticket %s", ticket_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Brak połączenia z API modelu.",
        ) from exc

    with session_scope() as session:
        tickets = SqlAlchemyTicketRepository(session)
        orders = SqlAlchemyOrderRepository(session)

        order = orders.get(classification.order_ref) if classification.order_ref else None
        policy = policy_engine.evaluate(
            intent=classification.intent,
            order=order,
            ticket_text=payload.text,
        )

        tickets.save_classification(ticket_id, classification)
        tickets.save_policy(ticket_id, policy)
        tickets.record_usage(ticket_id, "classification", usage)
        tickets.set_status(ticket_id, TicketStatus.TRIAGED.value)

    return TriageResponse(
        ticket_id=ticket_id,
        classification=ClassificationOut.from_domain(classification),
        order=OrderOut.from_domain(order) if order else None,
        policy=PolicyOut.from_domain(policy),
        usage=UsageOut.from_domain(usage),
    )


def _mark_failed(ticket_id: int) -> None:
    """Best-effort status update; never masks the original error."""
    try:
        with session_scope() as session:
            SqlAlchemyTicketRepository(session).set_status(ticket_id, TicketStatus.FAILED.value)
    except Exception:  # noqa: BLE001 - the caller is already raising something better
        logger.exception("Could not mark ticket %s as failed", ticket_id)
