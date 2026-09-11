"""Evaluate the ticket classifier against the labelled dataset.

Predictions are cached in eval/reports/. A second run re-reads them and costs nothing;
pass --refresh to call the model again.

Usage:
    python eval/run_eval.py                                   # live, model from config/app.yaml
    python eval/run_eval.py --models claude-sonnet-5 claude-haiku-4-5
    python eval/run_eval.py --limit 5                         # pilot: measure cost first
    python eval/run_eval.py --mode oracle                     # harness check, must be 100%
    python eval/run_eval.py --mode offline                    # keyword stub, no API key
"""

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import anthropic  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from ticket_triage.config import load_app_config  # noqa: E402
from ticket_triage.evaluation.dataset import load_dataset  # noqa: E402
from ticket_triage.evaluation.metrics import evaluate  # noqa: E402
from ticket_triage.evaluation.predictions import (  # noqa: E402
    OracleClassifier,
    load_run,
    new_run,
    run_predictions,
    save_run,
)
from ticket_triage.evaluation.report import _pct, render_eval  # noqa: E402
from ticket_triage.llm.classifier import AnthropicClassifier  # noqa: E402
from ticket_triage.llm.fake import FakeClassifier  # noqa: E402


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main() -> int:
    load_dotenv(ROOT / ".env")
    config = load_app_config()

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--models", nargs="+", default=[config.models.classification])
    parser.add_argument("--mode", choices=["live", "offline", "oracle"], default="live")
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--limit", type=int, default=None, help="Only the first N tickets (pilot run)."
    )
    parser.add_argument("--refresh", action="store_true", help="Ignore cached predictions.")
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval" / "dataset")
    parser.add_argument("--reports", type=Path, default=ROOT / "eval" / "reports")
    args = parser.parse_args()

    if args.mode == "live" and not (
        os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
    ):
        print(
            "Brak klucza API. Utwórz plik .env w katalogu projektu (skopiuj .env.example)\n"
            "i wpisz ANTHROPIC_API_KEY=... . Plik .env jest w .gitignore.\n"
            "Bez klucza możesz sprawdzić pipeline: --mode oracle albo --mode offline.",
            file=sys.stderr,
        )
        return 2

    dataset = load_dataset(args.dataset)
    tickets = dataset.tickets[: args.limit] if args.limit else dataset.tickets
    models = {"offline": ["fake"], "oracle": ["oracle"]}.get(args.mode, args.models)
    suffix = f"_limit{args.limit}" if args.limit else ""

    summaries = []
    for model in models:
        name = f"{args.mode}_{slug(model)}{suffix}"
        pred_path = args.reports / f"predictions_{name}.json"

        run = None
        if pred_path.exists() and not args.refresh:
            cached = load_run(pred_path)
            if cached.dataset_version == dataset.meta.version and cached.reps == args.reps:
                run = cached
                print(f"[{model}] używam zapisanych predykcji ({pred_path.name}) — bez wywołań API")

        if run is None:
            if args.mode == "live":
                client = anthropic.Anthropic(timeout=60.0, max_retries=4)
                classifier = AnthropicClassifier(
                    client,
                    model=model,
                    max_tokens=config.models.classification_max_tokens,
                    usd_to_pln=config.cost.usd_to_pln,
                )
            elif args.mode == "offline":
                classifier = FakeClassifier(usd_to_pln=config.cost.usd_to_pln)
            else:
                classifier = OracleClassifier(dataset.tickets)

            print(f"[{model}] klasyfikuję {len(tickets)} zgłoszeń × {args.reps} ...")
            predictions = run_predictions(classifier, tickets, reps=args.reps, workers=args.workers)
            run = new_run(
                model=model,
                mode=args.mode,
                dataset_version=dataset.meta.version,
                reps=args.reps,
                predictions=predictions,
            )
            save_run(run, pred_path)

        metrics = evaluate(tickets, run.predictions)
        (args.reports / f"eval_{name}.md").write_text(
            render_eval(
                run,
                metrics,
                ground_truth_source=dataset.meta.ground_truth_source,
                usd_to_pln=config.cost.usd_to_pln,
            ),
            encoding="utf-8",
        )
        (args.reports / f"eval_{name}.json").write_text(
            metrics.model_dump_json(indent=2), encoding="utf-8"
        )

        summaries.append((model, metrics))
        lo, hi = metrics.accuracy_strict_ci
        print(
            f"[{model}] accuracy {_pct(metrics.accuracy_strict)} "
            f"(95% CI {_pct(lo)}–{_pct(hi)}) · "
            f"baseline {_pct(metrics.majority_baseline)} · "
            f"ref {_pct(metrics.order_ref_accuracy)} · "
            f"brak odp. {metrics.n_no_answer} · "
            f"koszt ${metrics.total_cost_usd:.4f} → eval_{name}.md"
        )

    if len(summaries) > 1:
        intro = [
            "Ten sam zbiór testowy (`eval/dataset/tickets.jsonl`), uruchomiony osobno dla "
            "każdego modelu, żeby porównać jakość i koszt klasyfikacji. Szczegóły każdej "
            "kolumny — patrz plik `eval_{mode}_<model>.md` danego modelu (sekcja "
            '"Czym jest ten raport"). W skrócie:',
            "",
            "- **Accuracy / 95% CI** — trafność klasyfikacji i przedział ufności (Wilson).",
            "- **Łagodna** — trafność licząca zgłoszenia niejednoznaczne jako poprawne, "
            "jeśli model wskazał którąkolwiek z dopuszczalnych intencji.",
            "- **Nr zamówienia** — % poprawnie wyekstrahowanych numerów zamówień.",
            "- **ECE** — błąd kalibracji pewności (0% = deklarowana pewność modelu idealnie "
            "odpowiada jego faktycznej trafności).",
            "- **Koszt / zgłoszenie** — średni koszt jednego wywołania klasyfikatora w USD.",
            "- **p50** — mediana czasu odpowiedzi API w milisekundach.",
            "",
        ]
        rows = [
            "| Model | Accuracy | 95% CI | Łagodna | Nr zamówienia | ECE "
            "| Koszt / zgłoszenie | p50 |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for model, m in summaries:
            lo, hi = m.accuracy_strict_ci
            rows.append(
                f"| `{model}` | {_pct(m.accuracy_strict)} | {_pct(lo)}–{_pct(hi)} "
                f"| {_pct(m.accuracy_lenient)} | "
                f"{_pct(m.order_ref_accuracy)} | {_pct(m.expected_calibration_error)} | "
                f"${m.cost_per_row_usd:.6f} | {m.latency_ms_p50 or 0:.0f} ms |"
            )
        (args.reports / f"comparison_{args.mode}{suffix}.md").write_text(
            f"# Porównanie modeli ({args.mode})\n\n"
            + "\n".join(intro)
            + "\n"
            + "\n".join(rows)
            + "\n",
            encoding="utf-8",
        )
        print(f"porównanie → comparison_{args.mode}{suffix}.md")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
