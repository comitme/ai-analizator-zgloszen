"""HTTP request/response models.

Kept separate from ``domain.models`` on purpose: the wire format is allowed to
change (versioning, field renames for clients) without dragging the domain with it.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from ..domain.enums import (
    ESCALATION_LABELS_PL,
    Decision,
    EscalationReason,
    Intent,
    PolicyOutcome,
)
from ..domain.models import (
    Classification,
    DecisionResult,
    Order,
    PolicyResult,
    UsageRecord,
)
from ..domain.views import TicketSummary


class CreateTicketRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000, description="Raw customer message.")
    channel: str = Field(default="email", max_length=32)


class ClassificationOut(BaseModel):
    intent: Intent
    order_ref: str | None
    confidence: float
    reasoning: str

    @classmethod
    def from_domain(cls, c: Classification) -> "ClassificationOut":
        return cls(
            intent=c.intent,
            order_ref=c.order_ref,
            confidence=c.confidence,
            reasoning=c.reasoning,
        )


class OrderOut(BaseModel):
    order_ref: str
    purchase_date: date
    category: str
    amount_pln: Decimal

    @classmethod
    def from_domain(cls, o: Order) -> "OrderOut":
        return cls(
            order_ref=o.order_ref,
            purchase_date=o.purchase_date,
            category=o.category,
            amount_pln=o.amount_pln,
        )


class PolicyOut(BaseModel):
    outcome: PolicyOutcome
    reason_pl: str
    rule_id: str
    days_since_purchase: int | None
    high_value_order: bool
    legal_keywords_found: list[str]

    @classmethod
    def from_domain(cls, p: PolicyResult) -> "PolicyOut":
        return cls(**p.model_dump())


class DecisionOut(BaseModel):
    decision: Decision
    reasons: list[EscalationReason]
    reasons_pl: list[str] = Field(
        description="Same reasons in Polish, ready for the operator panel."
    )
    threshold_used: float

    @classmethod
    def from_domain(cls, d: DecisionResult) -> "DecisionOut":
        return cls(
            decision=d.decision,
            reasons=d.reasons,
            reasons_pl=[ESCALATION_LABELS_PL[r] for r in d.reasons],
            threshold_used=d.threshold_used,
        )


class UsageOut(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    cost_pln: Decimal

    @classmethod
    def from_domain(cls, u: UsageRecord) -> "UsageOut":
        return cls(
            model=u.model,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cost_usd=u.cost_usd,
            cost_pln=u.cost_pln,
        )


class TriageResponse(BaseModel):
    """The full pipeline result for one ticket."""

    ticket_id: int
    classification: ClassificationOut
    order: OrderOut | None
    policy: PolicyOut
    decision: DecisionOut
    draft_reply_pl: str | None = Field(
        default=None, description="Null whenever the ticket escalated."
    )
    usage: UsageOut = Field(description="Total across every model call for this ticket.")


# --- Operator panel ---------------------------------------------------------


class TicketListResponse(BaseModel):
    """A page of the queue plus the total, so the client can show 'x of y'."""

    total: int
    limit: int
    offset: int
    items: list[TicketSummary]


class OperatorAction(StrEnum):
    """What the human did with the draft. This is the live-traffic quality signal."""

    APPROVED = "approved"
    """Sent the generated draft unchanged - the model got it right."""

    EDITED = "edited"
    """Sent a corrected version - close, but not good enough."""

    REJECTED = "rejected"
    """Discarded the draft and handled it another way - the model was wrong."""


class ResolveTicketRequest(BaseModel):
    action: OperatorAction
    final_reply: str | None = Field(
        default=None,
        max_length=20_000,
        description=(
            "What was actually sent. Required for 'edited'; ignored for 'approved', "
            "where the stored draft is by definition what went out."
        ),
    )

    @model_validator(mode="after")
    def _an_edit_carries_its_text(self) -> "ResolveTicketRequest":
        if self.action is OperatorAction.EDITED and not (self.final_reply or "").strip():
            raise ValueError("final_reply jest wymagane przy akcji 'edited'")
        return self
