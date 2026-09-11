"""Generated replies, side by side with what the customer wrote.

A different question from the queue. The queue asks "what needs my decision now";
this asks "what quality of writing does this system produce" - the one thing the
evaluation set does not measure at all, because it only scores classification.

Reading a dozen of these is currently the only way to judge whether the replies are
good enough to put in front of a customer.
"""

import streamlit as st

from ui.api_client import TriageApiError
from ui.common import (
    INTENT_LABELS,
    POLICY_LABELS,
    confidence_badge,
    get_api,
    label,
    money,
    render_sidebar_status,
    show_api_error,
)

WIDOKI = {
    "Zwrot/reklamacja przyjęta": "allowed",
    "Odmowa (niezgodne z regulaminem)": "rejected",
    "Nie dotyczy regulaminu": "not_applicable",
    "Wszystkie z odpowiedzią": None,
}

st.title("✉️ Odpowiedzi modelu")
st.caption(
    "Jak system pisze do klientów. Ewaluacja mierzy tylko trafność klasyfikacji — "
    "jakość samych odpowiedzi ocenia się czytając je."
)
render_sidebar_status()

with st.sidebar:
    st.markdown("### Filtry")
    widok = st.radio("Sytuacja", list(WIDOKI), index=0)
    ile = st.slider("Ile przykładów", min_value=3, max_value=30, value=10, step=1)

api = get_api()
try:
    # Fetch a wider page than requested: the filter selects by policy outcome, but
    # only tickets that reached the generation step actually carry a reply.
    strona = api.list_tickets(policy_outcome=WIDOKI[widok], limit=min(200, ile * 6))
except TriageApiError as error:
    show_api_error(error)
    st.stop()

z_odpowiedzia = [t for t in strona["items"] if t["has_draft"]][:ile]

if not z_odpowiedzia:
    st.info(
        "Brak wygenerowanych odpowiedzi w tej kategorii.\n\n"
        "Odpowiedzi powstają tylko dla zgłoszeń obsłużonych automatycznie — "
        "eskalowane trafiają do człowieka bez szkicu, żeby nie płacić za tekst, "
        "którego nikt nie wyśle."
    )
    st.stop()

st.caption(
    f"{len(z_odpowiedzia)} z {strona['total']} zgłoszeń w tej kategorii ma wygenerowaną odpowiedź."
)

for podsumowanie in z_odpowiedzia:
    try:
        t = api.get_ticket(podsumowanie["id"])
    except TriageApiError as error:
        show_api_error(error)
        continue

    naglowek = (
        f"#{t['id']} · {label(INTENT_LABELS, t['intent'])} · "
        f"{label(POLICY_LABELS, t['policy_outcome'])}"
    )
    with st.expander(naglowek, expanded=len(z_odpowiedzia) <= 3):
        klient, system = st.columns(2)

        with klient:
            st.markdown("**Klient napisał**")
            st.text(t["raw_text"])
            st.caption(
                f"Rozpoznana intencja: {label(INTENT_LABELS, t['intent'])} · "
                f"pewność {confidence_badge(t['confidence'])}"
            )

        with system:
            st.markdown("**Na czym oparta jest odpowiedź**")
            st.caption(f"{t['policy_reason']}  \n`{t.get('policy_rule_id', '—')}`")
            if t.get("order_ref"):
                st.caption(
                    f"Zamówienie `{t['order_ref']}` · {t.get('order_category', '—')} · "
                    f"{t.get('order_amount_pln', '—')} zł · "
                    f"zakup {t.get('order_purchase_date', '—')}"
                )
            st.caption(f"Koszt: {money(t['cost_usd'])}")

        st.markdown("**Odpowiedź wygenerowana przez model**")
        st.info(t["draft_reply"])

        if t.get("operator_action"):
            st.success(f"Operator: {t['operator_action']}")
        else:
            st.caption("⏳ Nikt jeszcze tego nie zatwierdził — nic nie zostało wysłane do klienta.")

st.divider()
st.caption(
    "**Czego tu nie ma:** system nie wysyła maili. Powyższe to szkice czekające na "
    "zatwierdzenie w zakładce Kolejka — człowiek zostaje w pętli."
)
