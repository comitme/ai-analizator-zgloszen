# Porównanie modeli (live)

Ten sam zbiór testowy (`eval/dataset/tickets.jsonl`), uruchomiony osobno dla każdego modelu, żeby porównać jakość i koszt klasyfikacji. Szczegóły każdej kolumny — patrz plik `eval_{mode}_<model>.md` danego modelu (sekcja "Czym jest ten raport"). W skrócie:

- **Accuracy / 95% CI** — trafność klasyfikacji i przedział ufności (Wilson).
- **Łagodna** — trafność licząca zgłoszenia niejednoznaczne jako poprawne, jeśli model wskazał którąkolwiek z dopuszczalnych intencji.
- **Nr zamówienia** — % poprawnie wyekstrahowanych numerów zamówień.
- **ECE** — błąd kalibracji pewności (0% = deklarowana pewność modelu idealnie odpowiada jego faktycznej trafności).
- **Koszt / zgłoszenie** — średni koszt jednego wywołania klasyfikatora w USD.
- **p50** — mediana czasu odpowiedzi API w milisekundach.

| Model | Accuracy | 95% CI | Łagodna | Nr zamówienia | ECE | Koszt / zgłoszenie | p50 |
|---|---|---|---|---|---|---|---|
| `claude-sonnet-5` | 100.0% | 91.2%–100.0% | 100.0% | 100.0% | 9.9% | $0.004745 | 2386 ms |
| `claude-haiku-4-5` | 100.0% | 91.2%–100.0% | 100.0% | 100.0% | 6.7% | $0.001893 | 2835 ms |
