"""Repository interfaces - the seam between business logic and storage.

Be honest about what this buys, because a reviewer will ask:

* SQLite -> PostgreSQL needs **none** of this. That is a ``DATABASE_URL`` change,
  and the credit belongs to SQLAlchemy.
* These Protocols exist for the case where SQL runs out: pushing ticket history to
  BigQuery for analytics, or reading orders from the shop's REST API (Baselinker,
  Allegro) instead of a local table. Then ``OrderRepository`` gets an HTTP-backed
  implementation and no calling code changes.

Structural typing (``Protocol``) rather than inheritance: an implementation does not
need to import this module to satisfy it, which keeps test fakes trivial.
"""

from typing import Protocol, runtime_checkable

from ...domain.models import (
    Classification,
    DecisionResult,
    Order,
    PolicyResult,
    UsageRecord,
)
from ...domain.views import QueueMetrics, TicketDetail, TicketSummary


@runtime_checkable
class OrderRepository(Protocol):
    """Read-only access to shop orders."""

    def get(self, order_ref: str) -> Order | None:
        """Return the order, or ``None`` when the reference matches nothing."""
        ...


@runtime_checkable
class TicketRepository(Protocol):
    """Persistence for tickets and the pipeline's output."""

    def create(self, *, raw_text: str, channel: str) -> int:
        """Store an incoming ticket and return its id."""
        ...

    def save_classification(self, ticket_id: int, classification: Classification) -> None:
        """Attach the model's structured output to a ticket."""
        ...

    def save_policy(self, ticket_id: int, policy: PolicyResult) -> None:
        """Attach the deterministic policy verdict to a ticket."""
        ...

    def save_decision(self, ticket_id: int, decision: DecisionResult) -> None:
        """Attach the auto-vs-human decision and its reasons."""
        ...

    def save_draft_reply(self, ticket_id: int, reply: str) -> None:
        """Store the generated reply awaiting operator approval."""
        ...

    def record_usage(self, ticket_id: int, stage: str, usage: UsageRecord) -> None:
        """Append one LLM call's token counts and cost."""
        ...

    def set_status(self, ticket_id: int, status: str) -> None:
        """Move the ticket through its lifecycle."""
        ...

    def record_operator_action(
        self, ticket_id: int, *, action: str, final_reply: str | None
    ) -> None:
        """Close the ticket with the human's verdict (approved | edited | rejected)."""
        ...

    def list_tickets(
        self,
        *,
        status: str | None = None,
        decision: str | None = None,
        policy_outcome: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TicketSummary]:
        """Page through the queue, newest first."""
        ...

    def count_tickets(
        self,
        *,
        status: str | None = None,
        decision: str | None = None,
        policy_outcome: str | None = None,
    ) -> int:
        """Total matching the same filters, so the caller can paginate."""
        ...

    def get_detail(self, ticket_id: int) -> TicketDetail | None:
        """Everything known about one ticket, or ``None`` when the id is unknown."""
        ...

    def metrics(self, *, days: int | None = None) -> QueueMetrics:
        """Aggregate counts, automation rate and cost for the metrics page."""
        ...
