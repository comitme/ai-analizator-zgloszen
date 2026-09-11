"""The operator panel's read and resolve endpoints.

These back the Streamlit queue: list what needs attention, open one ticket, record
what the human decided.
"""

from ticket_triage.domain.enums import Intent

from .conftest import classification as _classification
from .conftest import override_classifier as _override_classifier


class TestQueueListing:
    def test_queue_returns_the_tickets_that_were_created(self, client):
        _override_classifier(_classification())
        client.post("/tickets", json={"text": "Zwrot butów, zamówienie 10432."})

        body = client.get("/tickets").json()

        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["preview"].startswith("Zwrot butów")

    def test_newest_ticket_comes_first(self, client):
        """An operator works the top of the queue, so the newest must be there."""
        _override_classifier(_classification())
        client.post("/tickets", json={"text": "Pierwsze zgłoszenie, zamówienie 10432."})
        client.post("/tickets", json={"text": "Drugie zgłoszenie, zamówienie 10432."})

        items = client.get("/tickets").json()["items"]

        assert [i["preview"].split()[0] for i in items] == ["Drugie", "Pierwsze"]

    def test_summary_carries_what_the_operator_triages_on(self, client):
        """The table must show why a ticket is waiting without opening it."""
        _override_classifier(_classification(confidence=0.4))
        client.post("/tickets", json={"text": "Niejasne, zamówienie 10432."})

        item = client.get("/tickets").json()["items"][0]

        assert item["intent"] == "return_no_reason"
        assert item["confidence"] == 0.4
        assert item["order_ref"] == "10432"
        assert item["decision"] == "escalate"
        assert item["escalation_reasons"] == ["low_confidence"]
        assert item["has_draft"] is False

    def test_auto_answered_ticket_reports_it_has_a_draft(self, client):
        _override_classifier(_classification())
        client.post("/tickets", json={"text": "Zwrot, zamówienie 10432."})

        item = client.get("/tickets").json()["items"][0]

        assert item["decision"] == "auto_reply"
        assert item["escalation_reasons"] == []
        assert item["has_draft"] is True


class TestQueueFilters:
    """The panel's whole point is showing only what needs a human right now."""

    def _seed_one_of_each(self, client):
        _override_classifier(_classification())
        client.post("/tickets", json={"text": "Automat, zamówienie 10432."})
        _override_classifier(_classification(confidence=0.4))
        client.post("/tickets", json={"text": "Eskalacja, zamówienie 10432."})

    def test_filtering_by_decision_returns_only_escalated(self, client):
        self._seed_one_of_each(client)

        body = client.get("/tickets", params={"decision": "escalate"}).json()

        assert body["total"] == 1
        assert [i["preview"].split(",")[0] for i in body["items"]] == ["Eskalacja"]

    def test_filtering_by_status_returns_only_that_status(self, client):
        self._seed_one_of_each(client)

        body = client.get("/tickets", params={"status": "triaged"}).json()

        assert body["total"] == 1
        assert body["items"][0]["status"] == "triaged"

    def test_total_counts_matches_and_ignores_the_page_size(self, client):
        """'3 of 12 shown' needs the total to survive the LIMIT."""
        _override_classifier(_classification())
        for i in range(3):
            client.post("/tickets", json={"text": f"Zgłoszenie {i}, zamówienie 10432."})

        body = client.get("/tickets", params={"limit": 2}).json()

        assert body["total"] == 3
        assert len(body["items"]) == 2

    def test_offset_walks_further_down_the_queue(self, client):
        _override_classifier(_classification())
        for i in range(3):
            client.post("/tickets", json={"text": f"Zgłoszenie {i}, zamówienie 10432."})

        first_page = client.get("/tickets", params={"limit": 2}).json()["items"]
        second_page = client.get("/tickets", params={"limit": 2, "offset": 2}).json()["items"]

        assert len(second_page) == 1
        assert {i["id"] for i in first_page}.isdisjoint({i["id"] for i in second_page})

    def test_unknown_status_is_rejected_rather_than_silently_ignored(self, client):
        """A typo in a filter must not look like an empty queue."""
        assert client.get("/tickets", params={"status": "nie-ma-takiego"}).status_code == 422


class TestTicketDetail:
    """Opening a ticket must show why the system decided what it decided."""

    def test_detail_shows_the_full_audit_trail(self, client):
        _override_classifier(_classification())
        ticket_id = client.post(
            "/tickets", json={"text": "Chcę zwrócić buty, zamówienie 10432."}
        ).json()["ticket_id"]

        body = client.get(f"/tickets/{ticket_id}").json()

        assert body["raw_text"].startswith("Chcę zwrócić buty")
        assert body["intent"] == "return_no_reason"
        assert body["reasoning"] == "test"
        assert body["policy_outcome"] == "allowed"
        assert body["policy_rule_id"] == "allowed.within_return_window"
        assert body["policy_reason"]
        assert body["decision"] == "auto_reply"
        assert body["draft_reply"].startswith("Dzień dobry")

    def test_detail_includes_the_order_the_decision_was_based_on(self, client):
        _override_classifier(_classification())
        ticket_id = client.post("/tickets", json={"text": "Zwrot, zamówienie 10432."}).json()[
            "ticket_id"
        ]

        body = client.get(f"/tickets/{ticket_id}").json()

        assert body["order_ref"] == "10432"
        assert body["order_category"] == "obuwie"
        assert body["order_amount_pln"] == "249.00"

    def test_detail_reports_what_the_ticket_cost(self, client):
        """Per-ticket cost is the number that makes the price per ticket concrete."""
        _override_classifier(_classification())
        ticket_id = client.post("/tickets", json={"text": "Zwrot, zamówienie 10432."}).json()[
            "ticket_id"
        ]

        body = client.get(f"/tickets/{ticket_id}").json()

        # Classification + generation, summed from the llm_calls rows.
        assert body["input_tokens"] == 600 + 700
        assert body["output_tokens"] == 120 + 250
        assert body["cost_usd"] == "0.006300"

    def test_escalated_ticket_reports_its_reasons_and_no_draft(self, client):
        _override_classifier(_classification(confidence=0.4))
        ticket_id = client.post("/tickets", json={"text": "Zamówienie 10432."}).json()["ticket_id"]

        body = client.get(f"/tickets/{ticket_id}").json()

        assert body["escalation_reasons"] == ["low_confidence"]
        assert body["draft_reply"] is None

    def test_unknown_ticket_is_a_404_from_our_handler(self, client):
        """Asserts on our own message, so this cannot pass merely because no route matched."""
        response = client.get("/tickets/424242")

        assert response.status_code == 404
        assert "424242" in response.json()["detail"]


class TestOperatorResolution:
    """Closing a ticket is where real ground truth enters the system."""

    def _auto_answered_ticket(self, client) -> int:
        _override_classifier(_classification())
        return client.post("/tickets", json={"text": "Zwrot, zamówienie 10432."}).json()[
            "ticket_id"
        ]

    def test_approving_a_draft_closes_the_ticket(self, client):
        ticket_id = self._auto_answered_ticket(client)

        body = client.post(f"/tickets/{ticket_id}/resolve", json={"action": "approved"}).json()

        assert body["operator_action"] == "approved"
        assert body["status"] == "answered"
        assert body["answered_at"] is not None

    def test_approving_keeps_the_draft_as_what_was_sent(self, client):
        """Approved means the draft went out unchanged - that is the sent text."""
        ticket_id = self._auto_answered_ticket(client)

        body = client.post(f"/tickets/{ticket_id}/resolve", json={"action": "approved"}).json()

        assert body["final_reply"] == body["draft_reply"]

    def test_editing_stores_the_corrected_text(self, client):
        ticket_id = self._auto_answered_ticket(client)

        body = client.post(
            f"/tickets/{ticket_id}/resolve",
            json={"action": "edited", "final_reply": "Poprawiona odpowiedź."},
        ).json()

        assert body["operator_action"] == "edited"
        assert body["final_reply"] == "Poprawiona odpowiedź."
        assert body["draft_reply"].startswith("Dzień dobry")  # original kept for comparison

    def test_editing_without_the_text_is_rejected(self, client):
        """An edit with nothing recorded teaches us nothing about what was wrong."""
        ticket_id = self._auto_answered_ticket(client)

        response = client.post(f"/tickets/{ticket_id}/resolve", json={"action": "edited"})

        assert response.status_code == 422

    def test_rejecting_records_the_verdict_without_inventing_a_reply(self, client):
        ticket_id = self._auto_answered_ticket(client)

        body = client.post(f"/tickets/{ticket_id}/resolve", json={"action": "rejected"}).json()

        assert body["operator_action"] == "rejected"
        assert body["final_reply"] is None
        assert body["status"] == "answered"

    def test_resolved_ticket_leaves_the_open_queue(self, client):
        ticket_id = self._auto_answered_ticket(client)
        client.post(f"/tickets/{ticket_id}/resolve", json={"action": "approved"})

        still_triaged = client.get("/tickets", params={"status": "triaged"}).json()

        assert still_triaged["total"] == 0

    def test_unknown_action_is_rejected(self, client):
        ticket_id = self._auto_answered_ticket(client)

        response = client.post(
            f"/tickets/{ticket_id}/resolve", json={"action": "wyslane-na-goraco"}
        )

        assert response.status_code == 422

    def test_resolving_an_unknown_ticket_is_a_404(self, client):
        response = client.post("/tickets/424242/resolve", json={"action": "approved"})

        assert response.status_code == 404
        assert "424242" in response.json()["detail"]


class TestPolicyOutcomeFilter:
    """Reply quality is judged separately for accepted and refused requests.

    A polite refusal and a confirmed return are different writing jobs, and the
    refusals are where a bad sentence costs a customer.
    """

    def _allowed_and_not_applicable(self, client):
        """A high-value order is NOT the counter-example: the policy still says the
        return is allowed, and the escalation happens one layer later, in the decision
        engine. A shipping question is what the policy genuinely has nothing to say
        about."""
        _override_classifier(_classification())
        client.post("/tickets", json={"text": "Zwrot butów, zamówienie 10432."})
        _override_classifier(_classification(intent=Intent.SHIPPING_STATUS))
        client.post("/tickets", json={"text": "Gdzie paczka, zamówienie 10432?"})

    def test_filtering_by_policy_outcome_returns_only_accepted(self, client):
        self._allowed_and_not_applicable(client)

        body = client.get("/tickets", params={"policy_outcome": "allowed"}).json()

        assert body["total"] == 1
        assert body["items"][0]["policy_outcome"] == "allowed"

    def test_summary_exposes_the_policy_outcome(self, client):
        _override_classifier(_classification())
        client.post("/tickets", json={"text": "Zwrot butów, zamówienie 10432."})

        assert client.get("/tickets").json()["items"][0]["policy_outcome"] == "allowed"

    def test_unknown_outcome_is_rejected(self, client):
        assert client.get("/tickets", params={"policy_outcome": "wymyslone"}).status_code == 422
