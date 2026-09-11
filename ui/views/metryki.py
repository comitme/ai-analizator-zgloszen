"""Metrics: is this system worth running?

Three questions, in the order a shop owner asks them: how much does it take off my
desk, do I trust what it sends, and what does it cost me per month.
"""

import pandas as pd
import streamlit as st

from ui.api_client import TriageApiError
from ui.common import (
    ESCALATION_LABELS,
    INTENT_LABELS,
    OPERATOR_ACTION_LABELS,
    STATUS_LABELS,
    get_api,
    label,
    money,
    percent,
    render_sidebar_status,
    show_api_error,
)

OKRESY = {"Ostatnie 7 dni": 7, "Ostatnie 30 dni": 30, "Od początku": None}
WOLUMENY = (100, 1_000, 10_000)


def bar_table(data: dict[str, int], mapping: dict[str, str], name: str) -> None:
    if not data:
        st.caption("Brak danych.")
        return
    frame = pd.DataFrame(
        {name: [label(mapping, k) for k in data], "Liczba": list(data.values())}
    ).sort_values("Liczba", ascending=False)
    st.bar_chart(frame.set_index(name), horizontal=True, height=max(140, 40 * len(frame)))


st.title("📊 Metryki")
render_sidebar_status()

with st.sidebar:
    st.markdown("### Okres")
    okres = st.radio("Zakres danych", list(OKRESY), index=2)

try:
    m = get_api().get_metrics(days=OKRESY[okres])
except TriageApiError as error:
    show_api_error(error)
    st.stop()

if m["total_tickets"] == 0:
    st.info(
        "Brak zgłoszeń w tym okresie. Przetwórz kilka na stronie głównej, żeby zobaczyć tu liczby."
    )
    st.stop()

# --- Nagłówek: cztery liczby, które decydują o sensie wdrożenia ---------------
k1, k2, k3, k4 = st.columns(4)
k1.metric("Zgłoszeń", f"{m['total_tickets']:,}".replace(",", " "))
k2.metric(
    "Automatyzacja",
    percent(m["automation_rate"]),
    help="Udział zgłoszeń obsłużonych bez człowieka. Reszta trafia do kolejki.",
)
k3.metric(
    "Szkice zaakceptowane",
    percent(m["draft_acceptance_rate"]),
    help=(
        "Odsetek szkiców wysłanych bez zmian. To jakość mierzona na prawdziwym ruchu, "
        "a nie na naszym własnym zbiorze ewaluacyjnym."
    ),
)
k4.metric("Koszt / zgłoszenie", money(m["cost"]["per_ticket_usd"]))

if m["draft_acceptance_rate"] is None:
    st.caption(
        "⚠️ Nikt jeszcze nie ocenił żadnego szkicu — dopóki operator nie zamknie "
        "zgłoszeń w kolejce, nie mamy pomiaru jakości na prawdziwym ruchu."
    )

st.divider()

# --- Rozkłady -----------------------------------------------------------------
lewa, prawa = st.columns(2)
with lewa:
    st.markdown("#### O co pytają klienci")
    bar_table(m["by_intent"], INTENT_LABELS, "Intencja")

    st.markdown("#### Status zgłoszeń")
    bar_table(m["by_status"], STATUS_LABELS, "Status")

with prawa:
    st.markdown("#### Dlaczego zgłoszenia trafiają do człowieka")
    bar_table(m["by_escalation_reason"], ESCALATION_LABELS, "Powód")
    st.caption(
        "Jedno zgłoszenie może mieć kilka powodów naraz, więc suma bywa większa "
        "niż liczba eskalacji."
    )

    st.markdown("#### Werdykty operatora")
    bar_table(m["by_operator_action"], OPERATOR_ACTION_LABELS, "Werdykt")

st.divider()

# --- Koszt --------------------------------------------------------------------
st.markdown("#### Koszt")
c1, c2, c3 = st.columns(3)
c1.metric("Razem", money(m["cost"]["total_usd"]), money(m["cost"]["total_pln"], "zł", places=2))
c2.metric(
    "Tokeny wejścia",
    f"{m['cost']['input_tokens']:,}".replace(",", " "),
)
c3.metric(
    "Tokeny wyjścia",
    f"{m['cost']['output_tokens']:,}".replace(",", " "),
)

podzial_l, podzial_p = st.columns(2)
with podzial_l:
    st.markdown("**Wg etapu**")
    st.caption("Klasyfikacja działa na każdym zgłoszeniu; generacja tylko na automatycznych.")
    st.dataframe(
        pd.DataFrame(
            [{"Etap": k, "Koszt USD": float(v)} for k, v in m["cost"]["by_stage"].items()]
        ),
        hide_index=True,
        use_container_width=True,
    )
with podzial_p:
    st.markdown("**Wg modelu**")
    st.dataframe(
        pd.DataFrame(
            [{"Model": k, "Koszt USD": float(v)} for k, v in m["cost"]["by_model"].items()]
        ),
        hide_index=True,
        use_container_width=True,
    )

# --- Prognoza -----------------------------------------------------------------
st.markdown("#### Ile kosztowałby większy ruch")
st.caption(
    "Prosta ekstrapolacja obecnego kosztu na zgłoszenie. Zakłada podobny rozkład "
    "zgłoszeń - przy innym miksie intencji udział droższej generacji się zmieni."
)
per_ticket = float(m["cost"]["per_ticket_usd"])
st.dataframe(
    pd.DataFrame(
        [
            {
                "Zgłoszeń / mies.": f"{volume:,}".replace(",", " "),
                "Koszt USD": round(per_ticket * volume, 2),
                "Koszt PLN": round(per_ticket * volume * 4.05, 2),
            }
            for volume in WOLUMENY
        ]
    ),
    hide_index=True,
    use_container_width=True,
)
