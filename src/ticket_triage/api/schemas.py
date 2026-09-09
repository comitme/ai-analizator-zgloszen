"""HTTP request/response models.

Kept separate from ``domain.models`` on purpose: the wire format is allowed to
change (versioning, field renames for clients) without dragging the domain with it.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from ..domain.enums import Intent, PolicyOutcome
from ..domain.models import Classification, Order, PolicyResult, UsageRecord


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
    """What Stage 2 returns: classification + facts + policy verdict.

    ``decision`` and ``draft_reply`` arrive in Stage 3.
    """

    ticket_id: int
    classification: ClassificationOut
    order: OrderOut | None
    policy: PolicyOut
    usage: UsageOut
