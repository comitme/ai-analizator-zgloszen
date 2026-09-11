"""Shared pieces for the Streamlit pages: the API handle, labels and formatting.

Polish labels are defined here rather than imported from ``ticket_triage.domain``
on purpose. The panel is a separate service that only speaks HTTP - importing the
application package would quietly couple the two containers together and make the
"UI could be rewritten in anything" claim false. The duplication is small, and the
enum values it maps are a stable API contract.
"""

from decimal import Decimal, InvalidOperation

import streamlit as st

from .api_client import TriageApi, TriageApiError

INTENT_LABELS = {
    "quality_complaint": "Reklamacja jakości",
    "return_no_reason": "Zwrot bez podania przyczyny",
    "shipping_status": "Status wysyłki",
    "refund_status": "Status zwrotu pieniędzy",
    "other": "Inne",
}

ESCALATION_LABELS = {
    "low_confidence": "Niska pewność klasyfikacji",
    "unknown_intent": "Nierozpoznana intencja",
    "order_not_found": "Nie znaleziono zamówienia",
    "ambiguous_policy": "Niejednoznaczna ocena regulaminu",
    "high_value_order": "Zamówienie o wysokiej wartości",
    "legal_keyword": "Sygnał sporu prawnego",
    "generation_failed": "Nie udało się wygenerować odpowiedzi",
}

STATUS_LABELS = {
    "new": "Nowe",
    "triaged": "Szkic gotowy",
    "escalated": "Do obsługi przez człowieka",
    "answered": "Zamknięte",
    "failed": "Błąd przetwarzania",
}

POLICY_LABELS = {
    "allowed": "Zgodne z regulaminem",
    "rejected": "Niezgodne z regulaminem",
    "ambiguous": "Niejednoznaczne",
    "not_applicable": "Nie dotyczy regulaminu",
}

DECISION_LABELS = {
    "auto_reply": "Odpowiedź automatyczna",
    "escalate": "Do człowieka",
}

OPERATOR_ACTION_LABELS = {
    "approved": "Zaakceptowano",
    "edited": "Poprawiono",
    "rejected": "Odrzucono",
}


@st.cache_resource
def get_api() -> TriageApi:
    """One client per Streamlit session, reusing its connection pool."""
    return TriageApi()


def label(mapping: dict[str, str], value: str | None, default: str = "—") -> str:
    """Look up a Polish label, falling back to the raw value.

    Never raises on an unknown key: a newer API version adding an enum member must
    not blank out the operator's queue.
    """
    if not value:
        return default
    return mapping.get(value, value)


def money(value, currency: str = "$", places: int = 4) -> str:
    """Format an amount that arrived as JSON.

    Always goes through ``Decimal(str(...))``: the API serialises Decimal columns as
    JSON *strings*, and formatting a string with ``f"{value:.4f}"`` raises. Every
    money field in the panel goes through here so that cannot happen in one forgotten
    place.
    """
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "—"
    formatted = f"{amount:.{places}f}"
    return f"{currency}{formatted}" if currency == "$" else f"{formatted} {currency}"


def percent(value: float | None) -> str:
    """``None`` stays visible as 'brak danych' - it is not the same as 0%."""
    return "brak danych" if value is None else f"{value * 100:.1f}%"


def confidence_badge(value: float | None) -> str:
    if value is None:
        return "—"
    mark = "🟢" if value >= 0.9 else "🟡" if value >= 0.75 else "🔴"
    return f"{mark} {value:.0%}"


def show_api_error(error: TriageApiError) -> None:
    """One consistent way to report a failed call, with a hint when it is a connection problem."""
    st.error(str(error))
    if error.status_code is None:
        st.caption(
            "Uruchom API: `make run` lub `docker compose up`. "
            "Adres można zmienić zmienną `TRIAGE_API_URL`."
        )


def render_sidebar_status() -> None:
    """Show which shop and model the API is running with, or that it is unreachable."""
    with st.sidebar:
        st.markdown("### Stan usługi")
        try:
            health = get_api().health()
        except TriageApiError as error:
            st.error("API niedostępne")
            st.caption(str(error))
            return

        st.success("API działa")
        st.caption(f"Sklep: **{health.get('shop', '—')}**")
        st.caption(f"Model: `{health.get('classification_model', '—')}`")
        if health.get("fake_llm"):
            st.warning("Tryb offline: odpowiedzi z atrapy, bez wywołań modelu.", icon="🧪")
