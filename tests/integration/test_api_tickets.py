"""End-to-end test of POST /tickets with a stubbed classifier.

Exercises the real FastAPI app, the real policy engine and a real SQLite database.
The only thing replaced is the model call - so this proves the wiring, not the model.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ticket_triage.api.deps import get_classifier, get_policy_engine
from ticket_triage.api.main import app
from ticket_triage.db.schema import LlmCallRow, OrderRow, TicketRow
from ticket_triage.db.session import init_engine, session_scope
from ticket_triage.domain.enums import Intent, PolicyOutcome
from ticket_triage.domain.models import Classification, UsageRecord
from ticket_triage.policy.engine import PolicyEngine

from ..conftest import TODAY


class StubClassifier:
    """Returns whatever the test tells it to, and reports a plausible token cost."""

    def __init__(self, classification: Classification) -> None:
        self.classification = classification

    def classify(self, ticket_text: str) -> tuple[Classification, UsageRecord]:
        return self.classification, UsageRecord(
            model="claude-sonnet-5",
            input_tokens=600,
            output_tokens=120,
            cost_usd=Decimal("0.0024"),
            cost_pln=Decimal("0.00972"),
        )


@pytest.fixture
def client(tmp_path, policy, monkeypatch):
    """App wired to a throwaway database and a stubbed classifier."""
    init_engine(f"sqlite:///{tmp_path / 'test.db'}")

    with session_scope() as session:
        session.add(
            OrderRow(
                order_ref="10432",
                purchase_date=TODAY.replace(day=TODAY.day - 3),
                category="obuwie",
                amount_pln=Decimal("249.00"),
            )
        )

    app.dependency_overrides[get_policy_engine] = lambda: PolicyEngine(policy)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _override_classifier(classification: Classification) -> None:
    app.dependency_overrides[get_classifier] = lambda: StubClassifier(classification)


def test_ticket_with_known_order_is_evaluated_against_the_policy(client):
    _override_classifier(
        Classification(
            intent=Intent.RETURN_NO_REASON,
            order_ref="10432",
            confidence=0.91,
            reasoning="Klient chce oddać towar.",
        )
    )

    response = client.post("/tickets", json={"text": "Chcę zwrócić buty, zamówienie 10432."})
    assert response.status_code == 201

    body = response.json()
    assert body["classification"]["intent"] == "return_no_reason"
    assert body["order"]["order_ref"] == "10432"
    assert body["policy"]["outcome"] == PolicyOutcome.ALLOWED.value
    assert body["usage"]["input_tokens"] == 600


def test_unknown_order_yields_ambiguous_policy(client):
    _override_classifier(
        Classification(
            intent=Intent.RETURN_NO_REASON,
            order_ref="99999",
            confidence=0.88,
            reasoning="Klient chce oddać towar.",
        )
    )

    body = client.post("/tickets", json={"text": "Zwrot, zamówienie 99999."}).json()
    assert body["order"] is None
    assert body["policy"]["outcome"] == PolicyOutcome.AMBIGUOUS.value
    assert body["policy"]["rule_id"] == "ambiguous.order_missing"


def test_everything_is_persisted(client):
    _override_classifier(
        Classification(
            intent=Intent.QUALITY_COMPLAINT,
            order_ref="10432",
            confidence=0.95,
            reasoning="Wada produktu.",
        )
    )

    ticket_id = client.post("/tickets", json={"text": "Podeszwa pękła, zamówienie 10432."}).json()[
        "ticket_id"
    ]

    with session_scope() as session:
        ticket = session.get(TicketRow, ticket_id)
        assert ticket.status == "triaged"
        assert ticket.intent == "quality_complaint"
        assert ticket.confidence == 0.95
        assert ticket.policy_outcome == "allowed"
        assert ticket.order_ref == "10432"

        calls = session.scalars(
            select(LlmCallRow).where(LlmCallRow.ticket_id == ticket_id)
        ).all()
        assert len(calls) == 1
        assert calls[0].stage == "classification"
        assert calls[0].input_tokens == 600


def test_hallucinated_order_ref_does_not_break_the_insert(client):
    """A made-up order number must not violate the foreign key."""
    _override_classifier(
        Classification(
            intent=Intent.RETURN_NO_REASON,
            order_ref="NIE-ISTNIEJE-123",
            confidence=0.6,
            reasoning="Zmyślony numer.",
        )
    )

    ticket_id = client.post("/tickets", json={"text": "Zwrot."}).json()["ticket_id"]

    with session_scope() as session:
        assert session.get(TicketRow, ticket_id).order_ref is None


def test_empty_text_is_rejected_by_validation(client):
    assert client.post("/tickets", json={"text": ""}).status_code == 422


def test_health_reports_the_loaded_shop(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "shop" in body
