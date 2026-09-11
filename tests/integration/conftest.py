"""Shared wiring for the API integration tests.

The app under test is the real one: real routers, real policy engine, real decision
engine, real SQLite. Only the two model calls are stubbed, so a failure here means
our code is wrong - never that the model had a bad day.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from ticket_triage.api.deps import get_classifier, get_triage_service
from ticket_triage.api.main import app
from ticket_triage.db.schema import OrderRow
from ticket_triage.db.session import init_engine, session_scope
from ticket_triage.domain.enums import Intent
from ticket_triage.domain.models import Classification, UsageRecord
from ticket_triage.policy.engine import PolicyEngine
from ticket_triage.triage.decision import DecisionEngine
from ticket_triage.triage.service import TriageService

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


class StubResponder:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, **kwargs) -> tuple[str, UsageRecord]:
        self.calls += 1
        return "Dzień dobry, dziękujemy za wiadomość...", UsageRecord(
            model="claude-sonnet-5",
            input_tokens=700,
            output_tokens=250,
            cost_usd=Decimal("0.0039"),
            cost_pln=Decimal("0.0158"),
        )


@pytest.fixture
def responder() -> StubResponder:
    return StubResponder()


@pytest.fixture
def client(tmp_path, policy, responder):
    """App wired to a throwaway database and stubbed model calls."""
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
        session.add(
            OrderRow(
                order_ref="99001",
                purchase_date=TODAY.replace(day=TODAY.day - 3),
                category="elektronika",
                amount_pln=Decimal("4999.00"),
            )
        )

    app.dependency_overrides[get_triage_service] = lambda: TriageService(
        policy_engine=PolicyEngine(policy),
        decision_engine=DecisionEngine(0.75),
        responder=responder,
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def override_classifier(classification: Classification) -> None:
    """Point the app at a classifier that always returns ``classification``."""
    app.dependency_overrides[get_classifier] = lambda: StubClassifier(classification)


def classification(
    *, intent=Intent.RETURN_NO_REASON, ref="10432", confidence=0.91
) -> Classification:
    return Classification(intent=intent, order_ref=ref, confidence=confidence, reasoning="test")
