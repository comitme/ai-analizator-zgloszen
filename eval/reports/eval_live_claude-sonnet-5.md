# Ewaluacja klasyfikatora — `claude-sonnet-5`

- Tryb: **live**
- Wersja zbioru: 1 · powtórzenia: 1 · wierszy: 40
- Uruchomiono: 2026-09-11 11:07 UTC
- Źródło etykiet: Synthetic. Written and labelled by a model (Claude Opus 5) from the project's intent definitions, then reviewed against the classification prompt. Not human-verified. The models under evaluation (Claude Sonnet 5, Claude Haiku 4.5) are from the same family, so scores may be optimistic versus real customer traffic.

## Czym jest ten raport

Każdy wiersz zbioru testowego (`eval/dataset/tickets.jsonl`) to jedno zgłoszenie klienta z ręcznie ustaloną poprawną intencją i, jeśli dotyczy, numerem zamówienia. Ten raport porównuje odpowiedzi modelu `claude-sonnet-5` z tymi etykietami — bez żadnej generacji odpowiedzi, wyłącznie klasyfikacja.

**Legenda:**

- **Accuracy (ścisła)** — % zgłoszeń, w których model wskazał dokładnie tę samą intencję co etykieta.
- **Accuracy (łagodna)** — jak wyżej, ale dla zgłoszeń oznaczonych jako niejednoznaczne (`acceptable_intents` w datasetcie) każda z dopuszczalnych intencji liczy się jako poprawna.
- **95% CI (Wilson)** — przedział ufności na trafność. Przy małej próbce prawdziwa (populacyjna) trafność modelu może się mieścić gdziekolwiek w tym przedziale, nie tylko w punktowym wyniku.
- **Baseline klasy większościowej** — trafność, jaką dałoby zgadywanie zawsze tej samej, najczęstszej klasy. Punkt odniesienia: model musi wyraźnie go przebić, żeby wynik cokolwiek znaczył.
- **Poprawny numer zamówienia** — % zgłoszeń, w których numer zamówienia wyciągnięty z tekstu zgadza się z oczekiwanym.
- **Brak odpowiedzi** — zgłoszenia, w których model nie zwrócił użytecznej odpowiedzi (błąd API, odmowa, zły format JSON). To osobna kategoria — nie liczy się jako błędna klasyfikacja, tylko jako brak danych.
- **Precision / Recall / F1 (per klasa)** — Precision: spośród zgłoszeń przypisanych przez model do tej klasy, ile faktycznie do niej należało. Recall: spośród zgłoszeń faktycznie należących do tej klasy, ile model rozpoznał. F1: średnia harmoniczna obu.
- **Macierz pomyłek** — wiersze to prawdziwa etykieta, kolumny to predykcja modelu; liczby poza przekątną to konkretne pomyłki (który typ z którym był mylony).
- **Kalibracja pewności / ECE** — czy deklarowana pewność modelu (`confidence`, 0–1) odpowiada jego faktycznej trafności w danym przedziale. Expected Calibration Error = 0% oznacza idealną kalibrację; im wyżej, tym bardziej pewność modelu rozjeżdża się z rzeczywistością (w dowolną stronę — może być zarówno zbyt pewny siebie, jak i zbyt ostrożny).
- **Koszt i wydajność** — realne zużycie tokenów i koszt liczony wg cennika w `llm/pricing.py`, oraz czas odpowiedzi API (p50/p95 = mediana / 95. percentyl).

## Wynik główny

| Metryka | Wartość | 95% CI (Wilson) |
|---|---|---|
| Accuracy (ścisła) | **100.0%** | 91.2% – 100.0% |
| Accuracy (łagodna, przypadki niejednoznaczne) | 100.0% | 91.2% – 100.0% |
| Baseline klasy większościowej (`return_no_reason`) | 22.5% | — |
| Poprawny numer zamówienia | 100.0% | — |
| Brak odpowiedzi (błąd API / odmowa / zły format) | 0 z 40 | — |

## Per klasa

| Intencja | Support | Precision | Recall | F1 |
|---|---|---|---|---|
| `quality_complaint` | 9 | 100.0% | 100.0% | 100.0% |
| `return_no_reason` | 9 | 100.0% | 100.0% | 100.0% |
| `shipping_status` | 8 | 100.0% | 100.0% | 100.0% |
| `refund_status` | 7 | 100.0% | 100.0% | 100.0% |
| `other` | 7 | 100.0% | 100.0% | 100.0% |

## Macierz pomyłek

Wiersze: etykieta · kolumny: predykcja

| | `quality_complaint` | `return_no_reason` | `shipping_status` | `refund_status` | `other` |
|---|---|---|---|---|---|
| `quality_complaint` | 9 | 0 | 0 | 0 | 0 |
| `return_no_reason` | 0 | 9 | 0 | 0 | 0 |
| `shipping_status` | 0 | 0 | 8 | 0 | 0 |
| `refund_status` | 0 | 0 | 0 | 7 | 0 |
| `other` | 0 | 0 | 0 | 0 | 7 |

## Kalibracja pewności

| Przedział confidence | n | Accuracy | Śr. confidence |
|---|---|---|---|
| 0.00 – 0.50 | 1 | 100.0% | 45.0% |
| 0.50 – 0.75 | 0 | — | — |
| 0.75 – 0.90 | 7 | 100.0% | 82.1% |
| 0.90 – 1.00 | 32 | 100.0% | 93.2% |

Expected Calibration Error: **9.9%** (0% = idealna kalibracja).

## Koszt i wydajność

| | Wartość |
|---|---|
| Tokeny wejścia / wyjścia | 76,152 / 3,751 |
| Tokeny na wiersz (min / mediana / max) | 1949 / 1992 / 2193 |
| Koszt całego przebiegu | $0.1898 (0.7687 zł) |
| Koszt na zgłoszenie | $0.004745 |
| Latencja p50 / p95 | 2386 ms / 3521 ms |

_Latencja obejmuje ewentualne automatyczne ponowienia SDK._

## Błędy (0)

Brak błędów.
