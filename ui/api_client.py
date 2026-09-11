"""HTTP client for the triage API.

The panel never imports the application package. It only speaks HTTP, which is what
makes the two docker-compose services genuinely separate: the UI could be rewritten
in anything, and the API could move to another host, without either knowing.

This module owns one job beyond transport: turning failures into something an
operator can act on. A stack trace in the middle of a queue is not an answer.
"""

import os
from typing import Any

import httpx

DEFAULT_BASE_URL = os.getenv("TRIAGE_API_URL", "http://localhost:8000")
DEFAULT_TIMEOUT = float(os.getenv("TRIAGE_API_TIMEOUT", "60"))


class TriageApiError(Exception):
    """A request failed. ``message`` is Polish and safe to show in the UI."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TriageApi:
    """Thin wrapper over the API's routes.

    Returns parsed JSON rather than typed models: the panel renders tables and the
    schemas already live in the service. Duplicating them here would mean two places
    to change for every field.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport
        )

    # --- Routes -------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def create_ticket(self, text: str, *, channel: str = "email") -> dict[str, Any]:
        return self._request("POST", "/tickets", json={"text": text, "channel": channel})

    def list_tickets(
        self,
        *,
        status: str | None = None,
        decision: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/tickets",
            params=_present(status=status, decision=decision, limit=limit, offset=offset),
        )

    def get_ticket(self, ticket_id: int) -> dict[str, Any]:
        return self._request("GET", f"/tickets/{ticket_id}")

    def resolve_ticket(
        self, ticket_id: int, *, action: str, final_reply: str | None = None
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/tickets/{ticket_id}/resolve",
            json={"action": action, "final_reply": final_reply},
        )

    def get_metrics(self, *, days: int | None = None) -> dict[str, Any]:
        return self._request("GET", "/metrics", params=_present(days=days))

    # --- Transport ----------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise TriageApiError(
                "Przekroczono czas oczekiwania na odpowiedź API. "
                "Zgłoszenie mogło zostać przyjęte - sprawdź kolejkę przed ponowieniem."
            ) from exc
        except httpx.RequestError as exc:
            raise TriageApiError(
                f"Nie można połączyć się z API ({self._client.base_url}). "
                "Sprawdź, czy usługa działa."
            ) from exc

        if response.is_success:
            return response.json()
        raise TriageApiError(_explain(response), status_code=response.status_code)


def _present(**kwargs: Any) -> dict[str, Any]:
    """Drop unset filters.

    ``status=None`` would be sent literally as the string "None" and rejected by the
    enum-typed endpoint, so an unused filter has to disappear from the URL entirely.
    """
    return {k: v for k, v in kwargs.items() if v is not None}


def _explain(response: httpx.Response) -> str:
    """Turn an error response into one Polish sentence.

    Never returns the raw body: a 500 from a proxy is HTML, and pasting that into the
    panel tells an operator nothing.
    """
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None

    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):  # FastAPI validation errors
        messages = [str(item.get("msg", "")) for item in detail if isinstance(item, dict)]
        joined = "; ".join(m for m in messages if m)
        if joined:
            return f"Żądanie odrzucone: {joined}"

    return f"API zwróciło błąd {response.status_code}."
