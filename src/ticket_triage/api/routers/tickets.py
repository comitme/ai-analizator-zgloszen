"""Ticket intake and triage.

The router owns two things and delegates everything else: the transaction shape, and
the mapping between domain objects and the wire format. Reasoning lives in
``TriageService``; persistence lives in the repositories.

Note the three separate transactions. No database connection is held open across a
model call - on SQLite that hardly matters, but holding a pooled Postgres connection
for the seconds an API call takes is how a service runs out of connections under
load. Worth getting right while the shape is cheap to change.
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
from ...domain.enums import Decision, TicketStatus
from ...domain.models import Order
from ...llm.classifier import Classifier
from ...triage.service import TriageService
from ..deps import get_classifier, get_triage_service
from ..schemas import (
    ClassificationOut,
    CreateTicketRequest,
    DecisionOut,
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
    service: Annotated[TriageService, Depends(get_triage_service)],
) -> TriageResponse:
    """Accept a customer message and run it through the triage pipeline."""

    # --- 1. Store the message before anything can fail -----------------------
    # A model outage must never lose a customer email; it leaves a row in state
    # `new` to retry.
    with session_scope() as session:
        ticket_id = SqlAlchemyTicketRepository(session).create(
            raw_text=payload.text, channel=payload.channel
        )

    # --- 2. Classify (spends money) -----------------------------------------
    try:
        classification, classification_usage = classifier.classify(payload.text)
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

    # --- 3. Resolve the order (short read, own transaction) ------------------
    order: Order | None = None
    if classification.order_ref:
        with session_scope() as session:
            order = SqlAlchemyOrderRepository(session).get(classification.order_ref)

    # --- 4. Policy, decision, and a draft when the ticket can be auto-answered
    # May spend money again; the service handles its own generation failures by
    # degrading to escalation rather than throwing away the classification.
    outcome = service.run(
        ticket_text=payload.text, classification=classification, order=order
    )

    # --- 5. Persist everything in one transaction ----------------------------
    total_usage = classification_usage
    with session_scope() as session:
        tickets = SqlAlchemyTicketRepository(session)

        tickets.save_classification(ticket_id, classification)
        tickets.save_policy(ticket_id, outcome.policy)
        tickets.save_decision(ticket_id, outcome.decision)
        tickets.record_usage(ticket_id, "classification", classification_usage)

        if outcome.draft_reply_pl:
            tickets.save_draft_reply(ticket_id, outcome.draft_reply_pl)
        if outcome.generation_usage:
            tickets.record_usage(ticket_id, "generation", outcome.generation_usage)
            total_usage = classification_usage + outcome.generation_usage

        tickets.set_status(
            ticket_id,
            TicketStatus.TRIAGED.value
            if outcome.decision.decision is Decision.AUTO_REPLY
            else TicketStatus.ESCALATED.value,
        )

    return TriageResponse(
        ticket_id=ticket_id,
        classification=ClassificationOut.from_domain(classification),
        order=OrderOut.from_domain(order) if order else None,
        policy=PolicyOut.from_domain(outcome.policy),
        decision=DecisionOut.from_domain(outcome.decision),
        draft_reply_pl=outcome.draft_reply_pl,
        usage=UsageOut.from_domain(total_usage),
    )


def _mark_failed(ticket_id: int) -> None:
    """Best-effort status update; never masks the original error."""
    try:
        with session_scope() as session:
            SqlAlchemyTicketRepository(session).set_status(ticket_id, TicketStatus.FAILED.value)
    except Exception:  # noqa: BLE001 - the caller is already raising something better
        logger.exception("Could not mark ticket %s as failed", ticket_id)
