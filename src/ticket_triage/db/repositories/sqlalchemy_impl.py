"""SQLAlchemy-backed implementations of the repository protocols."""

from sqlalchemy.orm import Session

from ...domain.models import (
    Classification,
    DecisionResult,
    Order,
    PolicyResult,
    UsageRecord,
)
from ..schema import LlmCallRow, OrderRow, TicketRow


class SqlAlchemyOrderRepository:
    """Reads orders from the local ``orders`` table."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, order_ref: str) -> Order | None:
        row = self._session.get(OrderRow, order_ref.strip())
        if row is None:
            return None
        return Order(
            order_ref=row.order_ref,
            purchase_date=row.purchase_date,
            category=row.category,
            amount_pln=row.amount_pln,
            customer_email=row.customer_email,
        )


class SqlAlchemyTicketRepository:
    """Writes tickets, classifications, policy verdicts and per-call usage."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _require(self, ticket_id: int) -> TicketRow:
        row = self._session.get(TicketRow, ticket_id)
        if row is None:
            raise LookupError(f"Ticket {ticket_id} not found")
        return row

    def create(self, *, raw_text: str, channel: str = "email") -> int:
        row = TicketRow(raw_text=raw_text, channel=channel, status="new")
        self._session.add(row)
        self._session.flush()  # assigns the autoincrement id without committing
        return row.id

    def save_classification(self, ticket_id: int, classification: Classification) -> None:
        row = self._require(ticket_id)
        row.intent = classification.intent.value
        row.confidence = classification.confidence
        row.reasoning = classification.reasoning

        # Only link the FK when the reference actually resolves - a hallucinated or
        # mistyped order number must not break the insert.
        if classification.order_ref:
            ref = classification.order_ref.strip()
            row.order_ref = ref if self._session.get(OrderRow, ref) else None

    def save_policy(self, ticket_id: int, policy: PolicyResult) -> None:
        row = self._require(ticket_id)
        row.policy_outcome = policy.outcome.value
        row.policy_rule_id = policy.rule_id
        row.policy_reason = policy.reason_pl

    def save_decision(self, ticket_id: int, decision: DecisionResult) -> None:
        row = self._require(ticket_id)
        row.decision = decision.decision.value
        # Comma-joined rather than a child table: the list is short, bounded by the
        # enum, and only ever read back whole for one ticket. A join table would buy
        # nothing here. If reasons ever need aggregating across tickets, this is the
        # column to normalise.
        row.escalation_reasons = ",".join(r.value for r in decision.reasons) or None

    def save_draft_reply(self, ticket_id: int, reply: str) -> None:
        self._require(ticket_id).draft_reply = reply

    def record_usage(self, ticket_id: int, stage: str, usage: UsageRecord) -> None:
        self._session.add(
            LlmCallRow(
                ticket_id=ticket_id,
                stage=stage,
                model=usage.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
                cost_usd=usage.cost_usd,
                cost_pln=usage.cost_pln,
            )
        )

    def set_status(self, ticket_id: int, status: str) -> None:
        self._require(ticket_id).status = status
