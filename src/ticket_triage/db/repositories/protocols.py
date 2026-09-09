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

from ...domain.models import Classification, Order, PolicyResult, UsageRecord


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

    def record_usage(self, ticket_id: int, stage: str, usage: UsageRecord) -> None:
        """Append one LLM call's token counts and cost."""
        ...

    def set_status(self, ticket_id: int, status: str) -> None:
        """Move the ticket through its lifecycle."""
        ...
