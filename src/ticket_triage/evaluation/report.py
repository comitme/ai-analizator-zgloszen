"""Markdown rendering for evaluation and sweep results."""

from decimal import Decimal

from ..domain.enums import Intent
from .metrics import EvalMetrics
from .predictions import PredictionRun
from .sweep import SweepResult

_NOT_LIVE = "  ⚠️ *wyniki nie pochodzą z prawdziwego modelu*"


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def render_eval(
    run: PredictionRun, m: EvalMetrics, *, ground_truth_source: str, usd_to_pln: Decimal
) -> str:
    lo, hi = m.accuracy_strict_ci
    llo, lhi = m.accuracy_lenient_ci
    lines = [
        f"# Ewaluacja klasyfikatora — `{run.model}`",
        "",
        f"- Tryb: **{run.mode}**" + (_NOT_LIVE if run.mode != "live" else ""),
        f"- Wersja zbioru: {run.dataset_version} · powtórzenia: {run.reps} · wierszy: {m.n_rows}",
        f"- Uruchomiono: {run.created_at:%Y-%m-%d %H:%M} UTC",
        f"- Źródło etykiet: {ground_truth_source}",
        "",
        "## Czym jest ten raport",
        "",
        f"Każdy wiersz zbioru testowego (`eval/dataset/tickets.jsonl`) to jedno zgłoszenie "
        "klienta z ręcznie ustaloną poprawną intencją i, jeśli dotyczy, numerem zamówienia. "
        f"Ten raport porównuje odpowiedzi modelu `{run.model}` z tymi etykietami — bez żadnej "
        "generacji odpowiedzi, wyłącznie klasyfikacja.",
        "",
        "**Legenda:**",
        "",
        "- **Accuracy (ścisła)** — % zgłoszeń, w których model wskazał dokładnie tę samą "
        "intencję co etykieta.",
        "- **Accuracy (łagodna)** — jak wyżej, ale dla zgłoszeń oznaczonych jako "
        "niejednoznaczne (`acceptable_intents` w datasetcie) każda z dopuszczalnych intencji "
        "liczy się jako poprawna.",
        "- **95% CI (Wilson)** — przedział ufności na trafność. Przy małej próbce prawdziwa "
        "(populacyjna) trafność modelu może się mieścić gdziekolwiek w tym przedziale, nie "
        "tylko w punktowym wyniku.",
        "- **Baseline klasy większościowej** — trafność, jaką dałoby zgadywanie zawsze tej "
        "samej, najczęstszej klasy. Punkt odniesienia: model musi wyraźnie go przebić, żeby "
        "wynik cokolwiek znaczył.",
        "- **Poprawny numer zamówienia** — % zgłoszeń, w których numer zamówienia wyciągnięty "
        "z tekstu zgadza się z oczekiwanym.",
        "- **Brak odpowiedzi** — zgłoszenia, w których model nie zwrócił użytecznej "
        "odpowiedzi (błąd API, odmowa, zły format JSON). To osobna kategoria — nie liczy się "
        "jako błędna klasyfikacja, tylko jako brak danych.",
        "- **Precision / Recall / F1 (per klasa)** — Precision: spośród zgłoszeń "
        "przypisanych przez model do tej klasy, ile faktycznie do niej należało. Recall: "
        "spośród zgłoszeń faktycznie należących do tej klasy, ile model rozpoznał. F1: "
        "średnia harmoniczna obu.",
        "- **Macierz pomyłek** — wiersze to prawdziwa etykieta, kolumny to predykcja modelu; "
        "liczby poza przekątną to konkretne pomyłki (który typ z którym był mylony).",
        "- **Kalibracja pewności / ECE** — czy deklarowana pewność modelu (`confidence`, "
        "0–1) odpowiada jego faktycznej trafności w danym przedziale. Expected Calibration "
        "Error = 0% oznacza idealną kalibrację; im wyżej, tym bardziej pewność modelu "
        "rozjeżdża się z rzeczywistością (w dowolną stronę — może być zarówno zbyt pewny "
        "siebie, jak i zbyt ostrożny).",
        "- **Koszt i wydajność** — realne zużycie tokenów i koszt liczony wg cennika w "
        "`llm/pricing.py`, oraz czas odpowiedzi API (p50/p95 = mediana / 95. percentyl).",
        "",
        "## Wynik główny",
        "",
        "| Metryka | Wartość | 95% CI (Wilson) |",
        "|---|---|---|",
        f"| Accuracy (ścisła) | **{_pct(m.accuracy_strict)}** | {_pct(lo)} – {_pct(hi)} |",
        f"| Accuracy (łagodna, przypadki niejednoznaczne) | {_pct(m.accuracy_lenient)} "
        f"| {_pct(llo)} – {_pct(lhi)} |",
        f"| Baseline klasy większościowej (`{m.majority_intent.value}`) "
        f"| {_pct(m.majority_baseline)} | — |",
        f"| Poprawny numer zamówienia | {_pct(m.order_ref_accuracy)} | — |",
        f"| Brak odpowiedzi (błąd API / odmowa / zły format) | {m.n_no_answer} z {m.n_rows} | — |",
    ]
    if len(m.per_rep_accuracy) > 1:
        reps = ", ".join(_pct(a) for a in m.per_rep_accuracy)
        lines.append(f"| Accuracy per powtórzenie | {reps} | — |")

    lines += [
        "",
        "## Per klasa",
        "",
        "| Intencja | Support | Precision | Recall | F1 |",
        "|---|---|---|---|---|",
    ]
    for c in m.per_class:
        lines.append(
            f"| `{c.intent.value}` | {c.support} | {_pct(c.precision)} "
            f"| {_pct(c.recall)} | {_pct(c.f1)} |"
        )

    intents = [i.value for i in Intent]
    lines += ["", "## Macierz pomyłek", "", "Wiersze: etykieta · kolumny: predykcja", ""]
    lines.append("| | " + " | ".join(f"`{i}`" for i in intents) + " |")
    lines.append("|---" * (len(intents) + 1) + "|")
    for exp in intents:
        cells = " | ".join(str(m.confusion[exp][pred]) for pred in intents)
        lines.append(f"| `{exp}` | {cells} |")

    lines += [
        "",
        "## Kalibracja pewności",
        "",
        "| Przedział confidence | n | Accuracy | Śr. confidence |",
        "|---|---|---|---|",
    ]
    for b in m.calibration:
        lines.append(
            f"| {b.low:.2f} – {b.high:.2f} | {b.n} "
            f"| {_pct(b.accuracy)} | {_pct(b.mean_confidence)} |"
        )
    lines.append("")
    lines.append(
        f"Expected Calibration Error: **{_pct(m.expected_calibration_error)}** "
        "(0% = idealna kalibracja)."
    )

    cost_pln = m.total_cost_usd * usd_to_pln
    t_min, t_median, t_max = m.tokens_per_row
    lines += [
        "",
        "## Koszt i wydajność",
        "",
        "| | Wartość |",
        "|---|---|",
        f"| Tokeny wejścia / wyjścia | {m.total_input_tokens:,} / {m.total_output_tokens:,} |",
        f"| Tokeny na wiersz (min / mediana / max) | {t_min} / {t_median:.0f} / {t_max} |",
        f"| Koszt całego przebiegu | ${m.total_cost_usd:.4f} ({cost_pln:.4f} zł) |",
        f"| Koszt na zgłoszenie | ${m.cost_per_row_usd:.6f} |",
        f"| Latencja p50 / p95 | {m.latency_ms_p50 or 0:.0f} ms / {m.latency_ms_p95 or 0:.0f} ms |",
        "",
        "_Latencja obejmuje ewentualne automatyczne ponowienia SDK._",
    ]

    lines += ["", f"## Błędy ({len(m.errors)})", ""]
    if not m.errors:
        lines.append("Brak błędów.")
    for e in m.errors:
        predicted = e.predicted_intent.value if e.predicted_intent else None
        lines.append(
            f"- **{e.ticket_id}** ({e.kind}) — "
            f"oczekiwano `{e.expected_intent.value}`/`{e.expected_order_ref}`, "
            f"otrzymano `{predicted}`/`{e.predicted_order_ref}`, "
            f"conf={e.confidence}\n  > {e.text}\n  > _{e.detail or ''}_"
        )
    return "\n".join(lines) + "\n"


def render_sweep(model: str, mode: str, s: SweepResult, current_threshold: float) -> str:
    recommended = (
        s.recommended_threshold
        if s.recommended_threshold is not None
        else "żaden nie mieści się w budżecie"
    )
    lines = [
        f"# Próg pewności — `{model}`",
        "",
        f"- Tryb: **{mode}**" + (_NOT_LIVE if mode != "live" else ""),
        f"- Sufit automatyzacji przy idealnej klasyfikacji: **{_pct(s.automation_ceiling)}** "
        "(reszta i tak trafia do człowieka przez twarde reguły)",
        f"- Budżet błędu automatycznych odpowiedzi: {_pct(s.max_auto_error_rate)}",
        f"- Obecny próg w `config/app.yaml`: **{current_threshold}**",
        f"- Rekomendowany próg: **{recommended}**",
        "",
        "## Czym jest ten raport",
        "",
        "Próg pewności (`confidence_threshold`) decyduje, czy zgłoszenie z daną pewnością "
        "modelu trafia do automatycznej odpowiedzi, czy do człowieka. Ten raport testuje "
        "wiele wartości progu na już policzonych predykcjach modelu (plik "
        f"`predictions_{mode}_{model}.json`) — nie woła ponownie API, więc jest darmowy do "
        "przeliczenia dowolną ilość razy.",
        "",
        "**Legenda:**",
        "",
        "- **Próg** — testowana wartość `confidence_threshold`; poniżej niej zgłoszenie "
        "zawsze trafia do człowieka, niezależnie od pozostałych reguł.",
        "- **Auto** — ile z N zgłoszeń zostałoby obsłużonych automatycznie przy tym progu "
        "(X/N), licząc też twarde reguły biznesowe (kwota, słowa prawne, brak zamówienia w "
        "bazie, kategoria wykluczona z regulaminu) — nie tylko sam próg pewności.",
        "- **Automatyzacja** — kolumna Auto jako % wszystkich zgłoszeń.",
        "- **Błędne auto** — ile automatycznie obsłużonych zgłoszeń miało błędną intencję "
        "lub błędny numer zamówienia.",
        "- **Błąd wśród auto** — Błędne auto jako % samych automatycznych odpowiedzi. To "
        "ryzyko z perspektywy klienta, który dostał auto-odpowiedź: jak często taka "
        "odpowiedź jest błędna.",
        "- **Błędne auto / wszystkie** — Błędne auto jako % całego ruchu (wszystkich "
        "zgłoszeń, nie tylko automatycznych). To ryzyko z perspektywy całego wolumenu.",
        "- **Sufit automatyzacji** — maksymalna możliwa automatyzacja przy idealnej (100% "
        "trafnej) klasyfikacji. Reszta zgłoszeń i tak trafia do człowieka przez twarde "
        "reguły biznesowe, niezależnie od tego, jak dobry jest model — to jest limit, "
        "którego żaden próg ani model nie przebije.",
        '- **Budżet błędu** — maksymalny akceptowalny "Błąd wśród auto", jaki bierze pod '
        "uwagę rekomendacja progu (parametr `--max-error`, domyślnie 5%).",
        "- **Rekomendowany próg** — próg dający największą automatyzację, nie przekraczając "
        "budżetu błędu; jeśli kilka progów daje ten sam wynik, wybierany jest najwyższy "
        "(bezpieczniejszy) z nich.",
        "",
        "| Próg | Auto | Automatyzacja | Błędne auto | Błąd wśród auto | Błędne auto / wszystkie |",
        "|---|---|---|---|---|---|",
    ]
    for r in s.rows:
        mark = " ◀ obecny" if abs(r.threshold - current_threshold) < 1e-9 else ""
        lines.append(
            f"| {r.threshold:.2f}{mark} | {r.auto}/{r.n} | {_pct(r.automation_rate)} "
            f"| {r.auto_wrong} | {_pct(r.auto_error_rate)} | {_pct(r.wrong_auto_per_ticket)} |"
        )
    return "\n".join(lines) + "\n"
