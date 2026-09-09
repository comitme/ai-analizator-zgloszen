"""The pure part of the pipeline: verdict, decision, and maybe a draft.

Deliberately knows nothing about the database or about HTTP. It takes an already
classified ticket plus its order (if any) and returns a :class:`TriageOutcome`. The
router owns transactions; this owns reasoning. That split is what makes the whole
decision path testable with three fakes and no I/O.
"""

import logging
from datetime import date

from ..domain.enums import Decision, EscalationReason
from ..domain.models import Classification, Order, TriageOutcome
from ..llm.responder import Responder
from ..policy.engine import PolicyEngine
from .decision import DecisionEngine

logger = logging.getLogger(__name__)


class TriageService:
    """Sequences policy -> decision -> (conditional) reply generation."""

    def __init__(
        self,
        *,
        policy_engine: PolicyEngine,
        decision_engine: DecisionEngine,
        responder: Responder,
    ) -> None:
        self._policy = policy_engine
        self._decision = decision_engine
        self._responder = responder

    def run(
        self,
        *,
        ticket_text: str,
        classification: Classification,
        order: Order | None,
        today: date | None = None,
    ) -> TriageOutcome:
        policy = self._policy.evaluate(
            intent=classification.intent,
            order=order,
            ticket_text=ticket_text,
            today=today,
        )
        decision = self._decision.decide(
            classification=classification, order=order, policy=policy
        )

        # Escalated tickets are not drafted at all. Nobody would send that reply, so
        # generating it would burn roughly three times the classification cost for
        # nothing - and would put a plausible-looking draft in front of an operator
        # who is supposed to be handling the case themselves.
        if decision.decision is not Decision.AUTO_REPLY:
            return TriageOutcome(policy=policy, decision=decision)

        try:
            reply, usage = self._responder.generate(
                ticket_text=ticket_text,
                classification=classification,
                order=order,
                policy=policy,
            )
        except Exception:
            # The classification and the verdict are still sound and already paid for.
            # Degrade to a human rather than failing the request and re-charging for
            # classification on the retry.
            logger.exception("Reply generation failed; escalating instead")
            return TriageOutcome(
                policy=policy,
                decision=DecisionEngine.force_escalation(
                    decision, EscalationReason.GENERATION_FAILED
                ),
            )

        return TriageOutcome(
            policy=policy,
            decision=decision,
            draft_reply_pl=reply,
            generation_usage=usage,
        )
