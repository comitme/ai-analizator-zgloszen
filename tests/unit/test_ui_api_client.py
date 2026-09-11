"""The Streamlit panel's HTTP client.

Worth testing on its own because it is the layer that decides what an operator sees
when the API is down, slow, or rejects a request. Streamlit pages then only lay out
whatever this returns.

Uses httpx's MockTransport rather than a mocking library: the real client code runs,
only the socket is replaced.
"""

import httpx
import pytest

from ui.api_client import TriageApi, TriageApiError


def _api(handler, **kwargs) -> TriageApi:
    return TriageApi("http://api:8000", transport=httpx.MockTransport(handler), **kwargs)


def _json_ok(payload: dict):
    return lambda request: httpx.Response(200, json=payload)


class TestRequestShape:
    def test_filters_are_sent_as_query_parameters(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(200, json={"total": 0, "limit": 50, "offset": 0, "items": []})

        _api(handler).list_tickets(status="escalated", limit=10)

        assert "status=escalated" in seen["url"]
        assert "limit=10" in seen["url"]

    def test_unset_filters_are_omitted_rather_than_sent_as_none(self):
        """`status=None` in the URL would be a 422 from the enum-typed endpoint."""
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(200, json={"total": 0, "limit": 50, "offset": 0, "items": []})

        _api(handler).list_tickets()

        assert "status" not in seen["url"]
        assert "decision" not in seen["url"]

    def test_resolving_sends_the_action_and_the_text(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = request.content.decode()
            return httpx.Response(200, json={"id": 1})

        _api(handler).resolve_ticket(1, action="edited", final_reply="Poprawione.")

        assert '"action": "edited"' in seen["body"] or '"action":"edited"' in seen["body"]
        assert "Poprawione." in seen["body"]


class TestErrorTranslation:
    """An operator is not reading stack traces - they need to know what to do next."""

    def test_unreachable_api_becomes_a_readable_polish_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        with pytest.raises(TriageApiError) as exc:
            _api(handler).get_metrics()

        assert "API" in str(exc.value)
        assert exc.value.status_code is None

    def test_timeout_is_reported_as_a_timeout_not_a_generic_failure(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow")

        with pytest.raises(TriageApiError) as exc:
            _api(handler).get_metrics()

        assert "czas" in str(exc.value).lower()

    def test_404_carries_the_status_code_so_the_page_can_react(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Zgłoszenie 42 nie istnieje."})

        with pytest.raises(TriageApiError) as exc:
            _api(handler).get_ticket(42)

        assert exc.value.status_code == 404
        assert "42" in str(exc.value)

    def test_validation_error_surfaces_why_the_request_was_rejected(self):
        """422 from ResolveTicketRequest must not read as 'something went wrong'."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                422,
                json={"detail": [{"loc": ["body"], "msg": "final_reply jest wymagane"}]},
            )

        with pytest.raises(TriageApiError) as exc:
            _api(handler).resolve_ticket(1, action="edited")

        assert "final_reply jest wymagane" in str(exc.value)

    def test_server_error_is_reported_without_leaking_html(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="<html>Internal Server Error</html>")

        with pytest.raises(TriageApiError) as exc:
            _api(handler).get_metrics()

        assert exc.value.status_code == 500
        assert "<html>" not in str(exc.value)


class TestResponses:
    def test_list_returns_the_parsed_payload(self):
        payload = {"total": 1, "limit": 50, "offset": 0, "items": [{"id": 7}]}

        assert _api(_json_ok(payload)).list_tickets() == payload

    def test_metrics_passes_the_day_window(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(200, json={"total_tickets": 0})

        _api(handler).get_metrics(days=7)

        assert "days=7" in seen["url"]
