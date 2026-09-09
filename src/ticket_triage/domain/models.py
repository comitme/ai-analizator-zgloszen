"""Domain models.

``Classification`` doubles as the LLM's output schema (passed to
``client.messages.parse(output_format=...)``), so its field descriptions are part
of the prompt contract - the model reads them. Keep them precise.

Everything else is plain transport between pipeline stages.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from .enums import Decision, EscalationReason, Intent, PolicyOutcome


class Classification(BaseModel):
    """Structured output of the classification call. This is the model's entire job."""

    intent: Intent = Field(
        description=(
            "Czego klient faktycznie chce. Wybierz JEDNĄ, najlepiej pasującą kategorię. "
            "Jeśli zgłoszenie nie pasuje do żadnej - wybierz 'other'."
        )
    )
    order_ref: str | None = Field(
        default=None,
        description=(
            "Numer zamówienia wprost podany w treści (same cyfry/znaki, bez słowa "
            "'zamówienie'). Jeśli klient go nie podał - null. Nie zgaduj i nie wymyślaj."
        ),
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Twoja pewność co do wybranej intencji, 0.0-1.0. Bądź szczery: obniż wartość, "
            "gdy zgłoszenie jest niejasne, zawiera dwie intencje naraz albo brakuje w nim "
            "kluczowych informacji."
        ),
    )
    reasoning: str = Field(
        description="Jedno zdanie po polsku: dlaczego ta intencja. Do wglądu dla operatora."
    )


class Order(BaseModel):
    """A shop order. In production this comes from the shop's real system."""

    order_ref: str
    purchase_date: date
    category: str
    amount_pln: Decimal
    customer_email: str | None = None


class PolicyResult(BaseModel):
    """Deterministic evaluation of the shop policy. Produced without calling any LLM."""

    outcome: PolicyOutcome
    reason_pl: str = Field(description="Human-readable justification, shown to the operator.")
    rule_id: str = Field(description="Stable id of the rule that decided, for auditing.")
    days_since_purchase: int | None = None

    # Facts for the decision layer. The policy engine detects them; DecisionEngine acts.
    high_value_order: bool = False
    legal_keywords_found: list[str] = Field(default_factory=list)


class UsageRecord(BaseModel):
    """Token usage and cost of a single LLM call."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    cost_pln: Decimal = Decimal("0")

    def __add__(self, other: "UsageRecord") -> "UsageRecord":
        """Sum two calls. Model label becomes '+'-joined when they differ."""
        return UsageRecord(
            model=self.model if self.model == other.model else f"{self.model}+{other.model}",
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
            cost_pln=self.cost_pln + other.cost_pln,
        )


class TriageResult(BaseModel):
    """Everything the pipeline produced for one ticket."""

    ticket_id: int
    classification: Classification
    order: Order | None = None
    policy: PolicyResult
    decision: Decision
    escalation_reasons: list[EscalationReason] = Field(default_factory=list)
    draft_reply_pl: str | None = None
    usage: UsageRecord
    created_at: datetime
