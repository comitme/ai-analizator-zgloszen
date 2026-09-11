"""Paste a customer message and watch the pipeline decide.

This is the demo surface. A shop owner pastes a real email here and sees exactly
what the system would have done with it - including what it would have cost and why
it did or did not answer on its own.
"""

import streamlit as st

from ui.api_client import TriageApiError
from ui.common import (
    DECISION_LABELS,
    ESCALATION_LABELS,
    INTENT_LABELS,
    POLICY_LABELS,
    confidence_badge,
    get_api,
    label,
    money,
    render_sidebar_status,
    show_api_error,
)

PRZYKLADY = {
    "Zwrot w terminie": (
        "Dzień dobry, chciałabym zwrócić buty z zamówienia 10432. Nie pasują rozmiarem."
    ),
    "Reklamacja": (
        "Kupiłem u Was słuchawki (zamówienie 10433) i po tygodniu przestał działać "
        "lewy kanał. Proszę o naprawę."
    ),
    "Status przesyłki": ("Dzień dobry, kiedy dotrze moje zamówienie 10434? Minęło już 5 dni."),
    "Sygnał prawny": "Zamówienie 10432 - żądam zwrotu, inaczej sprawę kieruję do UOKiK.",
}


def render_result(result: dict) -> None:
    classification = result["classification"]
    policy = result["policy"]
    decision = result["decision"]
    automatic = decision["decision"] == "auto_reply"

    if automatic:
        st.success("System odpowiedziałby automatycznie.", icon="🤖")
    else:
        st.warning("Zgłoszenie trafiłoby do człowieka.", icon="👤")

    left, right = st.columns([3, 2])

    with left:
        st.markdown("#### Co rozpoznał model")
        st.markdown(
            f"**Intencja:** {label(INTENT_LABELS, classification['intent'])}  \n"
            f"**Pewność:** {confidence_badge(classification['confidence'])}  \n"
            f"**Numer zamówienia:** `{classification['order_ref'] or 'nie podano'}`"
        )
        st.caption(f"Uzasadnienie modelu: {classification['reasoning']}")

        st.markdown("#### Ocena regulaminu (bez udziału modelu)")
        st.markdown(
            f"**Wynik:** {label(POLICY_LABELS, policy['outcome'])}  \n"
            f"**Reguła:** `{policy['rule_id']}`"
        )
        st.caption(policy["reason_pl"])

        if result.get("draft_reply_pl"):
            st.markdown("#### Proponowana odpowiedź")
            st.info(result["draft_reply_pl"])

    with right:
        st.markdown("#### Decyzja")
        st.markdown(f"**{label(DECISION_LABELS, decision['decision'])}**")
        if decision["reasons"]:
            st.markdown("Powody skierowania do człowieka:")
            for reason in decision["reasons"]:
                st.markdown(f"- {label(ESCALATION_LABELS, reason)}")
        st.caption(f"Zastosowany próg pewności: {decision['threshold_used']}")

        if result.get("order"):
            order = result["order"]
            st.markdown("#### Zamówienie z bazy")
            st.markdown(
                f"`{order['order_ref']}` · {order['category']}  \n"
                f"{order['amount_pln']} zł · zakup {order['purchase_date']}"
            )

        usage = result["usage"]
        st.markdown("#### Koszt tego zgłoszenia")
        st.metric("Koszt", money(usage["cost_usd"]), money(usage["cost_pln"], "zł"))
        st.caption(
            f"{usage['input_tokens']:,} tokenów wejścia · "
            f"{usage['output_tokens']:,} wyjścia · `{usage['model']}`".replace(",", " ")
        )


st.title("📮 Analizator zgłoszeń")
st.caption(
    "Wklej wiadomość od klienta. System rozpozna intencję, sprawdzi ją z regulaminem "
    "sklepu i albo przygotuje odpowiedź, albo przekaże sprawę człowiekowi."
)

render_sidebar_status()

wybor = st.selectbox(
    "Przykładowe zgłoszenie (opcjonalnie)", ["— wpiszę własne —", *PRZYKLADY], index=0
)
tresc = st.text_area(
    "Treść zgłoszenia",
    value=PRZYKLADY.get(wybor, ""),
    height=160,
    placeholder="Dzień dobry, chciałbym zwrócić...",
)

if st.button("Przeanalizuj", type="primary", disabled=not tresc.strip()):
    with st.spinner("Analizuję zgłoszenie..."):
        try:
            st.session_state["ostatni_wynik"] = get_api().create_ticket(tresc)
        except TriageApiError as error:
            st.session_state.pop("ostatni_wynik", None)
            show_api_error(error)

if wynik := st.session_state.get("ostatni_wynik"):
    st.divider()
    render_result(wynik)
    st.caption(
        f"Zapisano jako zgłoszenie #{wynik['ticket_id']}. "
        "Pełna historia jest w zakładce **Kolejka**."
    )
