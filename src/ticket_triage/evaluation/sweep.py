"""Confidence-threshold sweep: automation rate versus risk of a wrong automatic reply.

Runs the real PolicyEngine and DecisionEngine over saved predictions, so the numbers
include every hard escalation rule (legal keywords, high-value orders, unknown intent,
missing order) and not just the threshold. Costs nothing - no model calls.
"""

from datetime import date

from pydantic import BaseModel

from ..domain.enums import Decision
from ..domain.models import Classification, Order
from ..policy.engine import PolicyEngine
from ..triage.decision import DecisionEngine
from .dataset import EvalTicket
from .predictions import Prediction


class SweepRow(BaseModel):
    threshold: float
    n: int
    auto: int
    auto_wrong: int
    automation_rate: float
    auto_error_rate: float | None
    """Share of automatic replies that were wrong - the customer-facing risk."""
    wrong_auto_per_ticket: float
    """Wrong automatic replies over all tickets - risk at the level of total traffic."""


class SweepResult(BaseModel):
    rows: list[SweepRow]
    automation_ceiling: float
    """Automation with perfect classification: what the hard rules alone allow."""
    max_auto_error_rate: float
    recommended_threshold: float | None


def _norm(ref: str | None) -> str | None:
    return ref.strip() if ref and ref.strip() else None


def _auto(
    ticket_text: str,
    classification: Classification,
    orders: dict[str, Order],
    policy_engine: PolicyEngine,
    decision_engine: DecisionEngine,
    today: date,
) -> bool:
    # Production looks up the *predicted* reference, so a wrong ref flows through here too.
    ref = _norm(classification.order_ref)
    order = orders.get(ref) if ref else None
    policy = policy_engine.evaluate(
        intent=classification.intent, order=order, ticket_text=ticket_text, today=today
    )
    decision = decision_engine.decide(classification=classification, order=order, policy=policy)
    return decision.decision is Decision.AUTO_REPLY


def sweep(
    tickets: list[EvalTicket],
    predictions: list[Prediction],
    orders: dict[str, Order],
    policy_engine: PolicyEngine,
    *,
    today: date,
    thresholds: list[float] | None = None,
    max_auto_error_rate: float = 0.05,
) -> SweepResult:
    thresholds = thresholds or [round(i * 0.05, 2) for i in range(21)]
    by_id = {t.id: t for t in tickets}

    rows = []
    for threshold in thresholds:
        engine = DecisionEngine(threshold)
        auto = auto_wrong = 0
        for p in predictions:
            if p.status != "ok":
                continue  # no answer -> the ticket fails over to a human in production
            t = by_id[p.ticket_id]
            classification = Classification(
                intent=p.intent,
                order_ref=p.order_ref,
                confidence=p.confidence,
                reasoning=p.reasoning or "",
            )
            if _auto(t.text, classification, orders, policy_engine, engine, today):
                auto += 1
                wrong = p.intent != t.expected_intent or _norm(p.order_ref) != _norm(
                    t.expected_order_ref
                )
                auto_wrong += wrong
        n = len(predictions)
        rows.append(
            SweepRow(
                threshold=threshold,
                n=n,
                auto=auto,
                auto_wrong=auto_wrong,
                automation_rate=auto / n if n else 0.0,
                auto_error_rate=auto_wrong / auto if auto else None,
                wrong_auto_per_ticket=auto_wrong / n if n else 0.0,
            )
        )

    # Ceiling: gold labels at full confidence. Anything below this is lost to the model.
    ceiling_engine = DecisionEngine(0.0)
    ceiling_auto = sum(
        _auto(
            t.text,
            Classification(
                intent=t.expected_intent,
                order_ref=t.expected_order_ref,
                confidence=1.0,
                reasoning="",
            ),
            orders,
            policy_engine,
            ceiling_engine,
            today,
        )
        for t in tickets
    )

    # Most automation whose error rate stays within budget; ties go to the higher (safer) threshold.
    eligible = [
        r
        for r in rows
        if r.auto and r.auto_error_rate is not None and r.auto_error_rate <= max_auto_error_rate
    ]
    recommended = (
        max(eligible, key=lambda r: (r.automation_rate, r.threshold)).threshold
        if eligible
        else None
    )

    return SweepResult(
        rows=rows,
        automation_ceiling=ceiling_auto / len(tickets) if tickets else 0.0,
        max_auto_error_rate=max_auto_error_rate,
        recommended_threshold=recommended,
    )
