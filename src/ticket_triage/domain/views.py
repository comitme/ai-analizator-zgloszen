"""Read models for the operator panel.

Separate from ``domain.models`` on purpose. Those types flow *into* the pipeline and
get written to the database; these only ever flow *out* of it, assembled from rows
that already exist. Keeping them apart stops query-shaped fields (preview text,
counters, aggregates) from leaking into the objects the policy engine reasons about.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from .enums import Decision, EscalationReason, Intent, PolicyOutcome, TicketStatus


class TicketSummary(BaseModel):
    """One row in the operator queue. Deliberately small - the list view is a table.

    Carries enough to triage without opening the ticket: what the model thought, how
    sure it was, and why the ticket is waiting for a human.
    """

    id: int
    created_at: datetime
    status: TicketStatus
    preview: str = Field(description="First line of the customer message, for the table.")

    intent: Intent | None = None
    confidence: float | None = None
    order_ref: str | None = None

    policy_outcome: PolicyOutcome | None = None
    decision: Decision | None = None
    escalation_reasons: list[EscalationReason] = Field(default_factory=list)
    has_draft: bool = False


class TicketDetail(BaseModel):
    """Everything known about one ticket.

    The operator is being asked to trust (or override) an automated decision, so the
    whole chain is here: what the model read, what it concluded, which policy rule
    fired, why the ticket escalated, and what it cost.
    """

    id: int
    created_at: datetime
    status: TicketStatus
    channel: str
    raw_text: str

    intent: Intent | None = None
    confidence: float | None = None
    order_ref: str | None = None
    reasoning: str | None = None

    policy_outcome: PolicyOutcome | None = None
    policy_reason: str | None = None
    policy_rule_id: str | None = None

    decision: Decision | None = None
    escalation_reasons: list[EscalationReason] = Field(default_factory=list)
    draft_reply: str | None = None

    operator_action: str | None = None
    final_reply: str | None = Field(
        default=None, description="What actually went to the customer. None if nothing was sent."
    )
    answered_at: datetime | None = None

    order_purchase_date: date | None = None
    order_category: str | None = None
    order_amount_pln: Decimal | None = None

    cost_usd: Decimal = Decimal("0")
    cost_pln: Decimal = Decimal("0")
    input_tokens: int = 0
    output_tokens: int = 0


class CostBreakdown(BaseModel):
    """Money and tokens, sliced the two ways that answer different questions.

    ``by_model`` answers "is the cheaper model worth it"; ``by_stage`` answers "where
    does the spend go" - classification runs on every ticket, generation only on the
    ones we auto-answer.
    """

    total_usd: Decimal = Decimal("0")
    total_pln: Decimal = Decimal("0")
    per_ticket_usd: Decimal = Decimal("0")
    input_tokens: int = 0
    output_tokens: int = 0
    by_model: dict[str, Decimal] = Field(default_factory=dict)
    by_stage: dict[str, Decimal] = Field(default_factory=dict)
    calls_by_model: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "How many calls each model answered. Needed because cost alone cannot "
            "separate stub traffic from real: the offline stub costs exactly 0, which "
            "looks identical to 'no calls yet'. A projection built on stub rows would "
            "quietly read as free."
        ),
    )


class QueueMetrics(BaseModel):
    """Aggregates for the metrics page.

    Every number here is computed by the database (``GROUP BY``), not by loading rows
    into Python. At a few hundred tickets either approach works; the SQL one still
    works at a million.
    """

    period_days: int | None = Field(
        default=None, description="None means all time; otherwise the trailing window."
    )
    total_tickets: int = 0

    by_status: dict[str, int] = Field(default_factory=dict)
    by_decision: dict[str, int] = Field(default_factory=dict)
    by_intent: dict[str, int] = Field(default_factory=dict)
    by_escalation_reason: dict[str, int] = Field(default_factory=dict)
    by_operator_action: dict[str, int] = Field(default_factory=dict)

    automation_rate: float | None = Field(
        default=None,
        description=(
            "Share of triaged tickets answered without a human. None when nothing has "
            "been triaged - an empty queue has no rate, and 0.0 would read as failure."
        ),
    )
    draft_acceptance_rate: float | None = Field(
        default=None,
        description=(
            "Share of reviewed drafts an operator approved unchanged. The honest "
            "quality signal: measured on real traffic, not on our own eval set."
        ),
    )
    mean_confidence: float | None = None
    cost: CostBreakdown = Field(default_factory=CostBreakdown)
