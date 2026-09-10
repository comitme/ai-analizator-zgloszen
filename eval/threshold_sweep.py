"""Sweep the confidence threshold over saved predictions. Makes no API calls.

Run eval/run_eval.py first; this reads its prediction file.

Usage:
    python eval/threshold_sweep.py                          # live predictions, config model
    python eval/threshold_sweep.py --mode oracle
    python eval/threshold_sweep.py --max-error 0.02
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ticket_triage.config import load_app_config  # noqa: E402
from ticket_triage.evaluation.dataset import load_dataset  # noqa: E402
from ticket_triage.evaluation.predictions import load_run  # noqa: E402
from ticket_triage.evaluation.report import _pct, render_sweep  # noqa: E402
from ticket_triage.evaluation.sweep import sweep  # noqa: E402
from ticket_triage.policy.engine import PolicyEngine  # noqa: E402
from ticket_triage.policy.loader import load_return_policy  # noqa: E402


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main() -> int:
    config = load_app_config()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", default=config.models.classification)
    parser.add_argument("--mode", choices=["live", "offline", "oracle"], default="live")
    parser.add_argument(
        "--max-error", type=float, default=0.05, help="Budget for wrong automatic replies."
    )
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval" / "dataset")
    parser.add_argument("--reports", type=Path, default=ROOT / "eval" / "reports")
    args = parser.parse_args()

    model = {"offline": "fake", "oracle": "oracle"}.get(args.mode, args.model)
    name = f"{args.mode}_{slug(model)}"
    pred_path = args.reports / f"predictions_{name}.json"
    if not pred_path.exists():
        print(
            f"Brak {pred_path.name}. Najpierw: python eval/run_eval.py --mode {args.mode}",
            file=sys.stderr,
        )
        return 2

    dataset = load_dataset(args.dataset)
    run = load_run(pred_path)
    result = sweep(
        dataset.tickets,
        run.predictions,
        dataset.orders,
        PolicyEngine(load_return_policy()),
        today=dataset.meta.eval_date,
        max_auto_error_rate=args.max_error,
    )

    current = config.triage.confidence_threshold
    (args.reports / f"sweep_{name}.md").write_text(
        render_sweep(model, args.mode, result, current), encoding="utf-8"
    )
    (args.reports / f"sweep_{name}.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )

    at_current = next((r for r in result.rows if abs(r.threshold - current) < 1e-9), None)
    auto_rate = at_current.automation_rate if at_current else None
    error_rate = at_current.auto_error_rate if at_current else None
    print(
        f"[{model}] sufit automatyzacji {_pct(result.automation_ceiling)} · "
        f"przy progu {current}: automatyzacja {_pct(auto_rate)}, "
        f"błąd wśród auto {_pct(error_rate)} · "
        f"rekomendowany próg: {result.recommended_threshold} → sweep_{name}.md"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
