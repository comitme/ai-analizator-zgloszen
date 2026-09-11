"""Aggregates behind the metrics page.

These are the numbers the shop owner looks at to decide whether the system earns its
keep: how much it automates, how often the operator trusted it, what it costs.
"""

from decimal import Decimal

from .conftest import classification as _classification
from .conftest import override_classifier as _override_classifier


def _auto(client, text: str = "Zwrot, zamówienie 10432.") -> int:
    _override_classifier(_classification())
    return client.post("/tickets", json={"text": text}).json()["ticket_id"]


def _escalated(client, text: str = "Niejasne, zamówienie 10432.") -> int:
    _override_classifier(_classification(confidence=0.4))
    return client.post("/tickets", json={"text": text}).json()["ticket_id"]


class TestEmptyQueue:
    def test_no_tickets_reports_zero_not_an_error(self, client):
        body = client.get("/metrics").json()

        assert body["total_tickets"] == 0
        assert body["by_intent"] == {}

    def test_automation_rate_is_null_when_nothing_was_triaged(self, client):
        """0% would read as 'it automates nothing'. An empty queue has no rate at all."""
        assert client.get("/metrics").json()["automation_rate"] is None


class TestVolumeAndAutomation:
    def test_counts_every_ticket(self, client):
        _auto(client)
        _escalated(client)

        assert client.get("/metrics").json()["total_tickets"] == 2

    def test_automation_rate_is_the_share_answered_without_a_human(self, client):
        _auto(client)
        _escalated(client)
        _escalated(client)

        assert client.get("/metrics").json()["automation_rate"] == 1 / 3

    def test_decisions_and_statuses_are_broken_down(self, client):
        _auto(client)
        _escalated(client)

        body = client.get("/metrics").json()

        assert body["by_decision"] == {"auto_reply": 1, "escalate": 1}
        assert body["by_status"] == {"triaged": 1, "escalated": 1}

    def test_intent_distribution_is_reported(self, client):
        _auto(client)
        _auto(client)

        assert client.get("/metrics").json()["by_intent"] == {"return_no_reason": 2}

    def test_escalation_reasons_are_counted_individually(self, client):
        """The comma-joined column has to be split, or every combination looks unique."""
        _override_classifier(_classification(confidence=0.3, ref=None))
        client.post("/tickets", json={"text": "Chcę zwrot, sprawę prowadzi prawnik."})

        reasons = client.get("/metrics").json()["by_escalation_reason"]

        assert reasons == {"low_confidence": 1, "order_not_found": 1, "legal_keyword": 1}


class TestOperatorFeedback:
    def test_acceptance_rate_is_null_before_anyone_reviews(self, client):
        _auto(client)

        assert client.get("/metrics").json()["draft_acceptance_rate"] is None

    def test_acceptance_rate_counts_approvals_against_reviews(self, client):
        approved = _auto(client)
        edited = _auto(client)
        client.post(f"/tickets/{approved}/resolve", json={"action": "approved"})
        client.post(
            f"/tickets/{edited}/resolve",
            json={"action": "edited", "final_reply": "Poprawione."},
        )

        body = client.get("/metrics").json()

        assert body["draft_acceptance_rate"] == 0.5
        assert body["by_operator_action"] == {"approved": 1, "edited": 1}


class TestCost:
    def test_total_cost_sums_every_model_call(self, client):
        _auto(client)  # classification 0.0024 + generation 0.0039

        cost = client.get("/metrics").json()["cost"]

        assert Decimal(cost["total_usd"]) == Decimal("0.0063")
        assert cost["input_tokens"] == 600 + 700

    def test_cost_per_ticket_is_reported(self, client):
        _auto(client)
        _auto(client)

        cost = client.get("/metrics").json()["cost"]

        assert Decimal(cost["per_ticket_usd"]) == Decimal("0.0063")

    def test_cost_splits_by_stage_so_generation_spend_is_visible(self, client):
        _auto(client)
        _escalated(client)  # classification only - escalated tickets skip generation

        by_stage = client.get("/metrics").json()["cost"]["by_stage"]

        assert Decimal(by_stage["classification"]) == Decimal("0.0048")  # two tickets
        assert Decimal(by_stage["generation"]) == Decimal("0.0039")  # one ticket

    def test_cost_splits_by_model_for_comparing_them(self, client):
        _auto(client)

        by_model = client.get("/metrics").json()["cost"]["by_model"]

        assert Decimal(by_model["claude-sonnet-5"]) == Decimal("0.0063")

    def test_call_counts_per_model_are_reported(self, client):
        """Cost alone cannot tell stub traffic from real: the stub costs exactly 0,
        which is indistinguishable from 'no calls yet'. The panel needs counts to warn
        that a projection is built on data no model ever produced."""
        _auto(client)  # classification + generation

        calls = client.get("/metrics").json()["cost"]["calls_by_model"]

        assert calls == {"claude-sonnet-5": 2}
