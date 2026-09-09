"""SQLAlchemy 2.0 table definitions.

Three tables, each with one job:

* ``orders``    - facts the policy engine needs. Stands in for the shop's real system.
* ``tickets``   - one row per customer message, plus everything the pipeline decided.
* ``llm_calls`` - one row per model call, with tokens and cost. Feeds the metrics view.

``llm_calls`` is separate from ``tickets`` on purpose: a ticket costs one or more
calls, and cost analysis needs the per-call granularity (which model, which stage).
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class OrderRow(Base):
    """Shop order. Seeded synthetically; in production this is an API integration."""

    __tablename__ = "orders"

    order_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    purchase_date: Mapped[date]
    category: Mapped[str] = mapped_column(String(64), index=True)
    amount_pln: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    customer_email: Mapped[str | None] = mapped_column(String(255), default=None)


class TicketRow(Base):
    """A customer message and the pipeline's verdict on it."""

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # --- Input ---
    raw_text: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(32), default="email")
    status: Mapped[str] = mapped_column(String(32), index=True, default="new")

    # --- Classification (LLM) ---
    intent: Mapped[str | None] = mapped_column(String(32), index=True, default=None)
    order_ref: Mapped[str | None] = mapped_column(
        ForeignKey("orders.order_ref"), index=True, default=None
    )
    confidence: Mapped[float | None] = mapped_column(default=None)
    reasoning: Mapped[str | None] = mapped_column(Text, default=None)

    # --- Policy (deterministic) ---
    policy_outcome: Mapped[str | None] = mapped_column(String(32), default=None)
    policy_rule_id: Mapped[str | None] = mapped_column(String(64), default=None)
    policy_reason: Mapped[str | None] = mapped_column(Text, default=None)

    # --- Decision ---
    decision: Mapped[str | None] = mapped_column(String(32), index=True, default=None)
    escalation_reasons: Mapped[str | None] = mapped_column(
        String(255), default=None, doc="Comma-separated EscalationReason values."
    )

    # --- Output ---
    draft_reply: Mapped[str | None] = mapped_column(Text, default=None)

    # --- Operator feedback: the ground truth we accumulate over time ---
    operator_action: Mapped[str | None] = mapped_column(
        String(32), default=None, doc="approved | edited | rejected"
    )
    final_reply: Mapped[str | None] = mapped_column(Text, default=None)
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    order: Mapped[OrderRow | None] = relationship(lazy="joined")
    llm_calls: Mapped[list["LlmCallRow"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )


class LlmCallRow(Base):
    """One model invocation: which stage, which model, how many tokens, what it cost."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    stage: Mapped[str] = mapped_column(String(32), doc="classification | generation")
    model: Mapped[str] = mapped_column(String(64), index=True)

    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cache_read_tokens: Mapped[int] = mapped_column(default=0)
    cache_write_tokens: Mapped[int] = mapped_column(default=0)

    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    cost_pln: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))

    ticket: Mapped[TicketRow] = relationship(back_populates="llm_calls")
