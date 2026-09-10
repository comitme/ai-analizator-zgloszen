"""Collect classifier predictions for the evaluation set.

The runner calls the application's real ``Classifier.classify`` - the same object the
API uses - rather than re-implementing the model call, so the eval measures what
production ships.

Predictions are saved to disk and every metric is computed from that file. Paying for
the model once and re-slicing the results for free (metrics, threshold sweep) is the
cost-aware way to evaluate; re-running only happens on explicit request.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ..domain.enums import Intent
from ..domain.models import Classification, UsageRecord
from ..llm.classifier import Classifier
from .dataset import EvalTicket


class Prediction(BaseModel):
    """One classifier call on one ticket (one repetition)."""

    ticket_id: str
    rep: int = 0
    status: Literal["ok", "error"]
    """`error` means no usable answer (API failure, refusal, truncation, invalid output).
    It is reported separately and never counted as a wrong label - "no answer" is not a
    "negative answer"."""
    error: str | None = None
    intent: Intent | None = None
    order_ref: str | None = None
    confidence: float | None = None
    reasoning: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    latency_ms: float | None = None


class PredictionRun(BaseModel):
    model: str
    mode: Literal["live", "offline", "oracle"]
    dataset_version: int
    reps: int
    created_at: datetime
    predictions: list[Prediction]


class OracleClassifier:
    """Returns the gold label for every ticket.

    Harness check, not a model: pushed through the same metrics code it must score
    100%. Anything less means the eval pipeline itself is broken.
    """

    def __init__(self, tickets: list[EvalTicket]) -> None:
        self._by_text = {t.text: t for t in tickets}

    def classify(self, ticket_text: str) -> tuple[Classification, UsageRecord]:
        t = self._by_text[ticket_text]
        return (
            Classification(
                intent=t.expected_intent,
                order_ref=t.expected_order_ref,
                confidence=1.0,
                reasoning="oracle",
            ),
            UsageRecord(model="oracle"),
        )


def _predict_one(classifier: Classifier, ticket: EvalTicket, rep: int) -> Prediction:
    started = time.perf_counter()
    try:
        classification, usage = classifier.classify(ticket.text)
    except Exception as exc:  # noqa: BLE001 - every failure mode must become a row, not a crash
        return Prediction(
            ticket_id=ticket.id, rep=rep, status="error", error=f"{type(exc).__name__}: {exc}"
        )
    # Latency includes SDK-level retries; the report says so.
    latency_ms = (time.perf_counter() - started) * 1000

    if classification is None:  # e.g. a refusal leaves no parsed output
        return Prediction(
            ticket_id=ticket.id,
            rep=rep,
            status="error",
            error="no parsed output",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
            latency_ms=latency_ms,
        )

    return Prediction(
        ticket_id=ticket.id,
        rep=rep,
        status="ok",
        intent=classification.intent,
        order_ref=classification.order_ref,
        confidence=classification.confidence,
        reasoning=classification.reasoning,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cost_usd=usage.cost_usd,
        latency_ms=latency_ms,
    )


def run_predictions(
    classifier: Classifier,
    tickets: list[EvalTicket],
    *,
    reps: int = 1,
    workers: int = 4,
) -> list[Prediction]:
    """Classify every ticket ``reps`` times. Output order is deterministic (id, rep)."""
    jobs = [(t, r) for r in range(reps) for t in tickets]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(lambda job: _predict_one(classifier, *job), jobs))
    return sorted(results, key=lambda p: (p.ticket_id, p.rep))


def save_run(run: PredictionRun, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(run.model_dump_json(indent=2), encoding="utf-8")


def load_run(path: Path) -> PredictionRun:
    return PredictionRun.model_validate_json(path.read_text(encoding="utf-8"))


def new_run(
    *, model: str, mode: str, dataset_version: int, reps: int, predictions: list[Prediction]
) -> PredictionRun:
    return PredictionRun(
        model=model,
        mode=mode,
        dataset_version=dataset_version,
        reps=reps,
        created_at=datetime.now(UTC),
        predictions=predictions,
    )
