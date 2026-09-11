"""Operator queue: review what the system decided and close the ticket.

The panel exists so a human stays in the loop on everything the system was unsure
about - and so their verdict is recorded. Those verdicts are the only ground truth
collected from real traffic; the metrics page reads them back.
"""

import pandas as pd
import streamlit as st

from ui.api_client import TriageApiError
from ui.common import (
    DECISION_LABELS,
    ESCALATION_LABELS,
    INTENT_LABELS,
    OPERATOR_ACTION_LABELS,
    POLICY_LABELS,
    STATUS_LABELS,
    confidence_badge,
    get_api,
    label,
    money,
    render_sidebar_status,
    show_api_error,
)


def _when(timestamp: str) -> str:
    """ISO 8601 -> '2026-09-11 14:32'. Streamlit nie formatuje dat w tekście za nas."""
    return timestamp[:16].replace("T", " ")


WIDOKI = {
    "Wymaga człowieka": {"status": "escalated"},
    "Szkic do zatwierdzenia": {"status": "triaged"},
    "Zamknięte": {"status": "answered"},
    "Wszystkie": {},
}


def render_detail(ticket: dict) -> None:
    st.markdown(f"### Zgłoszenie #{ticket['id']}")
    st.caption(f"{label(STATUS_LABELS, ticket['status'])} · wpłynęło {_when(ticket['created_at'])}")

    st.markdown("**Treść od klienta**")
    st.text(ticket["raw_text"])

    left, right = st.columns(2)
    with left:
        st.markdown("**Klasyfikacja**")
        st.markdown(
            f"{label(INTENT_LABELS, ticket['intent'])} · {confidence_badge(ticket['confidence'])}"
        )
        if ticket.get("reasoning"):
            st.caption(ticket["reasoning"])

        st.markdown("**Ocena regulaminu**")
        st.markdown(label(POLICY_LABELS, ticket["policy_outcome"]))
        if ticket.get("policy_reason"):
            st.caption(f"{ticket['policy_reason']}  (`{ticket.get('policy_rule_id', '—')}`)")

    with right:
        st.markdown("**Decyzja systemu**")
        st.markdown(label(DECISION_LABELS, ticket["decision"]))
        for reason in ticket.get("escalation_reasons", []):
            st.markdown(f"- {label(ESCALATION_LABELS, reason)}")

        if ticket.get("order_ref"):
            st.markdown("**Zamówienie**")
            st.caption(
                f"`{ticket['order_ref']}` · {ticket.get('order_category', '—')} · "
                f"{ticket.get('order_amount_pln', '—')} zł · "
                f"zakup {ticket.get('order_purchase_date', '—')}"
            )

        st.caption(
            f"Koszt: {money(ticket['cost_usd'])} "
            f"({ticket['input_tokens']}/{ticket['output_tokens']} tokenów)"
        )


def render_actions(ticket: dict) -> None:
    """Approve, edit or reject - and record which, because that is the training signal."""
    if ticket.get("operator_action"):
        st.success(
            f"Zamknięte: **{label(OPERATOR_ACTION_LABELS, ticket['operator_action'])}**"
            f" ({_when(ticket['answered_at'])})"
        )
        if ticket.get("final_reply"):
            st.markdown("**Wysłana odpowiedź**")
            st.info(ticket["final_reply"])
        return

    st.markdown("### Twoja decyzja")
    if not ticket.get("draft_reply"):
        st.info(
            "System nie przygotował szkicu - to zgłoszenie wymaga odpowiedzi napisanej "
            "od zera. Wpisz treść poniżej i zapisz jako poprawioną."
        )

    tresc = st.text_area(
        "Odpowiedź do klienta",
        value=ticket.get("draft_reply") or "",
        height=200,
        key=f"tresc_{ticket['id']}",
    )
    zmieniona = tresc.strip() != (ticket.get("draft_reply") or "").strip()

    akceptuj, popraw, odrzuc = st.columns(3)
    api = get_api()

    def zamknij(action: str, final_reply: str | None = None) -> None:
        try:
            api.resolve_ticket(ticket["id"], action=action, final_reply=final_reply)
        except TriageApiError as error:
            show_api_error(error)
            return
        st.session_state.pop("wybrane_zgloszenie", None)
        st.rerun()

    with akceptuj:
        if st.button(
            "✅ Wyślij bez zmian",
            key=f"ok_{ticket['id']}",
            disabled=not ticket.get("draft_reply") or zmieniona,
            use_container_width=True,
            help="Aktywne, gdy szkic istnieje i nie został zmieniony.",
        ):
            zamknij("approved")

    with popraw:
        if st.button(
            "✏️ Zapisz poprawioną",
            key=f"edit_{ticket['id']}",
            type="primary",
            disabled=not tresc.strip() or not zmieniona,
            use_container_width=True,
        ):
            zamknij("edited", tresc)

    with odrzuc:
        if st.button(
            "🚫 Odrzuć szkic",
            key=f"no_{ticket['id']}",
            use_container_width=True,
            help="Szkic był nieprzydatny; sprawę obsłużono inaczej.",
        ):
            zamknij("rejected")


st.title("📥 Kolejka zgłoszeń")
render_sidebar_status()

with st.sidebar:
    st.markdown("### Filtry")
    widok = st.radio("Widok", list(WIDOKI), index=0)
    limit = st.slider("Ile wierszy", min_value=10, max_value=200, value=50, step=10)
    if st.button("Odśwież", use_container_width=True):
        st.session_state.pop("wybrane_zgloszenie", None)
        st.rerun()

api = get_api()
try:
    strona = api.list_tickets(**WIDOKI[widok], limit=limit)
except TriageApiError as error:
    show_api_error(error)
    st.stop()

st.caption(f"Pokazano {len(strona['items'])} z {strona['total']} zgłoszeń w tym widoku.")

if not strona["items"]:
    st.info("Brak zgłoszeń w tym widoku.")
    st.stop()

tabela = pd.DataFrame(
    [
        {
            "ID": t["id"],
            "Wpłynęło": _when(t["created_at"]),
            "Treść": t["preview"],
            "Intencja": label(INTENT_LABELS, t["intent"]),
            "Pewność": confidence_badge(t["confidence"]),
            "Decyzja": label(DECISION_LABELS, t["decision"]),
            "Powody": ", ".join(label(ESCALATION_LABELS, r) for r in t["escalation_reasons"]),
            "Status": label(STATUS_LABELS, t["status"]),
        }
        for t in strona["items"]
    ]
)
st.dataframe(tabela, use_container_width=True, hide_index=True)

st.divider()
identyfikatory = [t["id"] for t in strona["items"]]
wybrane = st.selectbox(
    "Otwórz zgłoszenie",
    identyfikatory,
    format_func=lambda i: f"#{i} — {next(t['preview'] for t in strona['items'] if t['id'] == i)}",
    key="wybrane_zgloszenie",
)

try:
    szczegoly = api.get_ticket(wybrane)
except TriageApiError as error:
    show_api_error(error)
    st.stop()

render_detail(szczegoly)
st.divider()
render_actions(szczegoly)
