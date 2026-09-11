"""SQLAlchemy-backed implementations of the repository protocols."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...domain.enums import (
    Decision,
    EscalationReason,
    Intent,
    PolicyOutcome,
    TicketStatus,
)
from ...domain.models import (
    Classification,
    DecisionResult,
    Order,
    PolicyResult,
    UsageRecord,
)
from ...domain.views import CostBreakdown, QueueMetrics, TicketDetail, TicketSummary
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

    def record_operator_action(
        self, ticket_id: int, *, action: str, final_reply: str | None
    ) -> None:
        """Close a ticket with what the human actually did.

        The only place real ground truth enters the system. ``approved`` means the
        model was right on live traffic; ``edited`` and ``rejected`` are labelled
        mistakes worth re-reading when tuning the prompt or the threshold.
        """
        row = self._require(ticket_id)
        row.operator_action = action
        row.final_reply = final_reply
        row.answered_at = datetime.now(UTC)
        row.status = TicketStatus.ANSWERED.value

    # --- Reads for the operator panel ---------------------------------------

    def list_tickets(
        self,
        *,
        status: str | None = None,
        decision: str | None = None,
        policy_outcome: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TicketSummary]:
        """Newest first, because an operator works the top of the queue.

        Ordered by id as well as timestamp: two tickets submitted in the same second
        get identical ``created_at`` values on SQLite, and "newest first" has to stay
        deterministic anyway.
        """
        stmt = _filtered(
            select(TicketRow), status=status, decision=decision, policy_outcome=policy_outcome
        )
        stmt = (
            stmt.order_by(TicketRow.created_at.desc(), TicketRow.id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = self._session.execute(stmt).unique().scalars().all()
        return [_to_summary(r) for r in rows]

    def count_tickets(
        self,
        *,
        status: str | None = None,
        decision: str | None = None,
        policy_outcome: str | None = None,
    ) -> int:
        """Total matching the same filters - the page size must not change it."""
        stmt = _filtered(
            select(func.count()).select_from(TicketRow),
            status=status,
            decision=decision,
            policy_outcome=policy_outcome,
        )
        return int(self._session.execute(stmt).scalar_one())

    def get_detail(self, ticket_id: int) -> TicketDetail | None:
        """One ticket with its full audit trail, or ``None`` when the id is unknown."""
        row = self._session.get(TicketRow, ticket_id)
        if row is None:
            return None

        cost_usd, cost_pln, tokens_in, tokens_out = self._session.execute(
            select(
                func.coalesce(func.sum(LlmCallRow.cost_usd), 0),
                func.coalesce(func.sum(LlmCallRow.cost_pln), 0),
                func.coalesce(func.sum(LlmCallRow.input_tokens), 0),
                func.coalesce(func.sum(LlmCallRow.output_tokens), 0),
            ).where(LlmCallRow.ticket_id == ticket_id)
        ).one()

        return TicketDetail(
            id=row.id,
            created_at=row.created_at,
            status=TicketStatus(row.status),
            channel=row.channel,
            raw_text=row.raw_text,
            intent=Intent(row.intent) if row.intent else None,
            confidence=row.confidence,
            order_ref=row.order_ref,
            reasoning=row.reasoning,
            policy_outcome=PolicyOutcome(row.policy_outcome) if row.policy_outcome else None,
            policy_reason=row.policy_reason,
            policy_rule_id=row.policy_rule_id,
            decision=Decision(row.decision) if row.decision else None,
            escalation_reasons=_split_reasons(row.escalation_reasons),
            draft_reply=row.draft_reply,
            operator_action=row.operator_action,
            final_reply=row.final_reply,
            answered_at=row.answered_at,
            order_purchase_date=row.order.purchase_date if row.order else None,
            order_category=row.order.category if row.order else None,
            order_amount_pln=row.order.amount_pln if row.order else None,
            cost_usd=Decimal(str(cost_usd)),
            cost_pln=Decimal(str(cost_pln)),
            input_tokens=int(tokens_in),
            output_tokens=int(tokens_out),
        )

    def metrics(self, *, days: int | None = None) -> QueueMetrics:
        """Aggregate the queue. Every count is a ``GROUP BY``, not a Python loop."""
        since = datetime.now(UTC) - timedelta(days=days) if days else None

        total = int(
            self._session.execute(_since(select(func.count(TicketRow.id)), since)).scalar_one()
        )
        by_status = self._group(TicketRow.status, since)
        by_decision = self._group(TicketRow.decision, since)
        by_intent = self._group(TicketRow.intent, since)
        by_operator_action = self._group(TicketRow.operator_action, since)

        # Reasons live comma-joined in one column, so they are split here rather than
        # in SQL. Only escalated rows are fetched, and only that one column.
        joined_reasons = self._session.execute(
            _since(
                select(TicketRow.escalation_reasons).where(
                    TicketRow.escalation_reasons.is_not(None)
                ),
                since,
            )
        ).scalars()
        by_reason: dict[str, int] = {}
        for joined in joined_reasons:
            for reason in _split_reasons(joined):
                by_reason[reason.value] = by_reason.get(reason.value, 0) + 1

        triaged = sum(by_decision.values())
        auto = by_decision.get(Decision.AUTO_REPLY.value, 0)
        reviewed = sum(by_operator_action.values())
        approved = by_operator_action.get("approved", 0)

        mean_confidence = self._session.execute(
            _since(
                select(func.avg(TicketRow.confidence)).where(TicketRow.confidence.is_not(None)),
                since,
            )
        ).scalar_one_or_none()

        return QueueMetrics(
            period_days=days,
            total_tickets=total,
            by_status=by_status,
            by_decision=by_decision,
            by_intent=by_intent,
            by_escalation_reason=dict(sorted(by_reason.items(), key=lambda kv: -kv[1])),
            by_operator_action=by_operator_action,
            automation_rate=auto / triaged if triaged else None,
            draft_acceptance_rate=approved / reviewed if reviewed else None,
            mean_confidence=float(mean_confidence) if mean_confidence is not None else None,
            cost=self._cost(since, total),
        )

    def _group(self, column, since: datetime | None) -> dict[str, int]:
        stmt = _since(
            select(column, func.count()).where(column.is_not(None)).group_by(column), since
        )
        return {str(value): int(count) for value, count in self._session.execute(stmt)}

    def _cost(self, since: datetime | None, total_tickets: int) -> CostBreakdown:
        totals = select(
            func.coalesce(func.sum(LlmCallRow.cost_usd), 0),
            func.coalesce(func.sum(LlmCallRow.cost_pln), 0),
            func.coalesce(func.sum(LlmCallRow.input_tokens), 0),
            func.coalesce(func.sum(LlmCallRow.output_tokens), 0),
        )
        if since is not None:
            totals = totals.where(LlmCallRow.created_at >= since)
        usd, pln, tokens_in, tokens_out = self._session.execute(totals).one()

        def sliced(column) -> dict[str, Decimal]:
            stmt = select(column, func.coalesce(func.sum(LlmCallRow.cost_usd), 0)).group_by(column)
            if since is not None:
                stmt = stmt.where(LlmCallRow.created_at >= since)
            return {str(key): Decimal(str(value)) for key, value in self._session.execute(stmt)}

        counted = select(LlmCallRow.model, func.count()).group_by(LlmCallRow.model)
        if since is not None:
            counted = counted.where(LlmCallRow.created_at >= since)

        total_usd = Decimal(str(usd))
        return CostBreakdown(
            total_usd=total_usd,
            total_pln=Decimal(str(pln)),
            per_ticket_usd=total_usd / total_tickets if total_tickets else Decimal("0"),
            input_tokens=int(tokens_in),
            output_tokens=int(tokens_out),
            by_model=sliced(LlmCallRow.model),
            by_stage=sliced(LlmCallRow.stage),
            calls_by_model={str(k): int(v) for k, v in self._session.execute(counted)},
        )


def _since(stmt, since: datetime | None):
    """Restrict a ticket query to the trailing window, if one was asked for."""
    return stmt.where(TicketRow.created_at >= since) if since is not None else stmt


def _filtered(stmt, *, status: str | None, decision: str | None, policy_outcome: str | None = None):
    """Apply the queue filters to any statement, so list and count cannot drift apart."""
    if status:
        stmt = stmt.where(TicketRow.status == status)
    if decision:
        stmt = stmt.where(TicketRow.decision == decision)
    if policy_outcome:
        stmt = stmt.where(TicketRow.policy_outcome == policy_outcome)
    return stmt


def _split_reasons(joined: str | None) -> list[EscalationReason]:
    """Parse the comma-joined column, skipping values this build does not know."""
    if not joined:
        return []
    parsed = []
    for token in joined.split(","):
        try:
            parsed.append(EscalationReason(token.strip()))
        except ValueError:  # written by a newer version - not worth crashing the queue
            continue
    return parsed


def _to_summary(row: TicketRow) -> TicketSummary:
    first_line = row.raw_text.strip().splitlines()[0] if row.raw_text.strip() else ""
    return TicketSummary(
        id=row.id,
        created_at=row.created_at,
        status=TicketStatus(row.status),
        preview=first_line[:120],
        intent=Intent(row.intent) if row.intent else None,
        confidence=row.confidence,
        order_ref=row.order_ref,
        policy_outcome=PolicyOutcome(row.policy_outcome) if row.policy_outcome else None,
        decision=Decision(row.decision) if row.decision else None,
        escalation_reasons=_split_reasons(row.escalation_reasons),
        has_draft=bool(row.draft_reply),
    )
