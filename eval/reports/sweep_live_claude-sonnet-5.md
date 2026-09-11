# Próg pewności — `claude-sonnet-5`

- Tryb: **live**
- Sufit automatyzacji przy idealnej klasyfikacji: **65.0%** (reszta i tak trafia do człowieka przez twarde reguły)
- Budżet błędu automatycznych odpowiedzi: 5.0%
- Obecny próg w `config/app.yaml`: **0.75**
- Rekomendowany próg: **0.45**

## Czym jest ten raport

Próg pewności (`confidence_threshold`) decyduje, czy zgłoszenie z daną pewnością modelu trafia do automatycznej odpowiedzi, czy do człowieka. Ten raport testuje wiele wartości progu na już policzonych predykcjach modelu (plik `predictions_live_claude-sonnet-5.json`) — nie woła ponownie API, więc jest darmowy do przeliczenia dowolną ilość razy.

**Legenda:**

- **Próg** — testowana wartość `confidence_threshold`; poniżej niej zgłoszenie zawsze trafia do człowieka, niezależnie od pozostałych reguł.
- **Auto** — ile z N zgłoszeń zostałoby obsłużonych automatycznie przy tym progu (X/N), licząc też twarde reguły biznesowe (kwota, słowa prawne, brak zamówienia w bazie, kategoria wykluczona z regulaminu) — nie tylko sam próg pewności.
- **Automatyzacja** — kolumna Auto jako % wszystkich zgłoszeń.
- **Błędne auto** — ile automatycznie obsłużonych zgłoszeń miało błędną intencję lub błędny numer zamówienia.
- **Błąd wśród auto** — Błędne auto jako % samych automatycznych odpowiedzi. To ryzyko z perspektywy klienta, który dostał auto-odpowiedź: jak często taka odpowiedź jest błędna.
- **Błędne auto / wszystkie** — Błędne auto jako % całego ruchu (wszystkich zgłoszeń, nie tylko automatycznych). To ryzyko z perspektywy całego wolumenu.
- **Sufit automatyzacji** — maksymalna możliwa automatyzacja przy idealnej (100% trafnej) klasyfikacji. Reszta zgłoszeń i tak trafia do człowieka przez twarde reguły biznesowe, niezależnie od tego, jak dobry jest model — to jest limit, którego żaden próg ani model nie przebije.
- **Budżet błędu** — maksymalny akceptowalny "Błąd wśród auto", jaki bierze pod uwagę rekomendacja progu (parametr `--max-error`, domyślnie 5%).
- **Rekomendowany próg** — próg dający największą automatyzację, nie przekraczając budżetu błędu; jeśli kilka progów daje ten sam wynik, wybierany jest najwyższy (bezpieczniejszy) z nich.

| Próg | Auto | Automatyzacja | Błędne auto | Błąd wśród auto | Błędne auto / wszystkie |
|---|---|---|---|---|---|
| 0.00 | 26/40 | 65.0% | 0 | 0.0% | 0.0% |
| 0.05 | 26/40 | 65.0% | 0 | 0.0% | 0.0% |
| 0.10 | 26/40 | 65.0% | 0 | 0.0% | 0.0% |
| 0.15 | 26/40 | 65.0% | 0 | 0.0% | 0.0% |
| 0.20 | 26/40 | 65.0% | 0 | 0.0% | 0.0% |
| 0.25 | 26/40 | 65.0% | 0 | 0.0% | 0.0% |
| 0.30 | 26/40 | 65.0% | 0 | 0.0% | 0.0% |
| 0.35 | 26/40 | 65.0% | 0 | 0.0% | 0.0% |
| 0.40 | 26/40 | 65.0% | 0 | 0.0% | 0.0% |
| 0.45 | 26/40 | 65.0% | 0 | 0.0% | 0.0% |
| 0.50 | 25/40 | 62.5% | 0 | 0.0% | 0.0% |
| 0.55 | 25/40 | 62.5% | 0 | 0.0% | 0.0% |
| 0.60 | 25/40 | 62.5% | 0 | 0.0% | 0.0% |
| 0.65 | 25/40 | 62.5% | 0 | 0.0% | 0.0% |
| 0.70 | 25/40 | 62.5% | 0 | 0.0% | 0.0% |
| 0.75 ◀ obecny | 25/40 | 62.5% | 0 | 0.0% | 0.0% |
| 0.80 | 23/40 | 57.5% | 0 | 0.0% | 0.0% |
| 0.85 | 23/40 | 57.5% | 0 | 0.0% | 0.0% |
| 0.90 | 19/40 | 47.5% | 0 | 0.0% | 0.0% |
| 0.95 | 11/40 | 27.5% | 0 | 0.0% | 0.0% |
| 1.00 | 0/40 | 0.0% | 0 | — | 0.0% |
