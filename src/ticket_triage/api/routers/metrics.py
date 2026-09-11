"""Queue aggregates for the metrics page.

Read-only and cheap: the database does the counting. Kept in its own router because
it answers a different question from ``/tickets`` - not "what needs attention" but
"is this system worth running".
"""

from typing import Annotated

from fastapi import APIRouter, Query

from ...db.repositories.sqlalchemy_impl import SqlAlchemyTicketRepository
from ...db.session import session_scope
from ...domain.views import QueueMetrics

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=QueueMetrics)
def get_metrics(
    days: Annotated[
        int | None,
        Query(ge=1, le=365, description="Okno czasowe w dniach. Pominięte = od początku."),
    ] = None,
) -> QueueMetrics:
    """Volume, automation rate, operator feedback and cost."""
    with session_scope() as session:
        return SqlAlchemyTicketRepository(session).metrics(days=days)
