"""Classification metrics computed from saved predictions.

Everything here is pure: tickets + predictions in, numbers out. No API, no disk.
"""

import math
import statistics
from collections import Counter
from decimal import Decimal

from pydantic import BaseModel

from ..domain.enums import Intent
from .dataset import EvalTicket
from .predictions import Prediction

CALIBRATION_BINS: list[tuple[float, float]] = [(0.0, 0.5), (0.5, 0.75), (0.75, 0.9), (0.9, 1.0001)]


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion.

    Preferred over the normal approximation because it stays inside [0, 1] and behaves
    at small n and extreme rates - exactly our situation with 40 cases.
    """
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


class ClassMetrics(BaseModel):
    intent: Intent
    support: int
    precision: float | None
    recall: float | None
    f1: float | None


class CalibrationBin(BaseModel):
    low: float
    high: float
    n: int
    accuracy: float | None
    mean_confidence: float | None


class ErrorCase(BaseModel):
    ticket_id: str
    rep: int
    kind: str  # "wrong_intent" | "wrong_order_ref" | "no_answer"
    text: str
    expected_intent: Intent
    predicted_intent: Intent | None
    expected_order_ref: str | None
    predicted_order_ref: str | None
    confidence: float | None
    detail: str | None


class EvalMetrics(BaseModel):
    n_rows: int
    n_ok: int
    n_no_answer: int
    accuracy_strict: float
    accuracy_strict_ci: tuple[float, float]
    accuracy_lenient: float
    accuracy_lenient_ci: tuple[float, float]
    majority_baseline: float
    majority_intent: Intent
    order_ref_accuracy: float
    per_rep_accuracy: list[float]
    per_class: list[ClassMetrics]
    confusion: dict[str, dict[str, int]]
    calibration: list[CalibrationBin]
    expected_calibration_error: float | None
    errors: list[ErrorCase]
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: Decimal
    cost_per_row_usd: Decimal
    tokens_per_row: tuple[int, float, int]  # min, median, max
    latency_ms_p50: float | None
    latency_ms_p95: float | None


def _norm_ref(ref: str | None) -> str | None:
    return ref.strip() if ref and ref.strip() else None


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return ordered[idx]


def evaluate(tickets: list[EvalTicket], predictions: list[Prediction]) -> EvalMetrics:
    by_id = {t.id: t for t in tickets}
    ok = [p for p in predictions if p.status == "ok"]
    n_ok = len(ok)

    strict = sum(1 for p in ok if p.intent == by_id[p.ticket_id].expected_intent)
    lenient = sum(1 for p in ok if p.intent in by_id[p.ticket_id].acceptable_intents)
    refs_ok = sum(
        1 for p in ok if _norm_ref(p.order_ref) == _norm_ref(by_id[p.ticket_id].expected_order_ref)
    )

    majority_intent, majority_count = Counter(t.expected_intent for t in tickets).most_common(1)[0]

    per_rep: dict[int, list[bool]] = {}
    for p in ok:
        per_rep.setdefault(p.rep, []).append(p.intent == by_id[p.ticket_id].expected_intent)

    per_class = []
    for intent in Intent:
        tp = sum(
            1 for p in ok if p.intent == intent and by_id[p.ticket_id].expected_intent == intent
        )
        predicted = sum(1 for p in ok if p.intent == intent)
        support = sum(1 for p in ok if by_id[p.ticket_id].expected_intent == intent)
        precision = tp / predicted if predicted else None
        recall = tp / support if support else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and (precision + recall) > 0
            else (0.0 if precision is not None and recall is not None else None)
        )
        per_class.append(
            ClassMetrics(intent=intent, support=support, precision=precision, recall=recall, f1=f1)
        )

    confusion: dict[str, dict[str, int]] = {i.value: {j.value: 0 for j in Intent} for i in Intent}
    for p in ok:
        confusion[by_id[p.ticket_id].expected_intent.value][p.intent.value] += 1

    calibration, ece_sum = [], 0.0
    for low, high in CALIBRATION_BINS:
        members = [p for p in ok if p.confidence is not None and low <= p.confidence < high]
        if members:
            acc = sum(p.intent == by_id[p.ticket_id].expected_intent for p in members) / len(
                members
            )
            conf = statistics.fmean(p.confidence for p in members)
            ece_sum += len(members) * abs(acc - conf)
        else:
            acc = conf = None
        calibration.append(
            CalibrationBin(
                low=low, high=min(high, 1.0), n=len(members), accuracy=acc, mean_confidence=conf
            )
        )

    errors: list[ErrorCase] = []
    for p in predictions:
        t = by_id[p.ticket_id]
        if p.status != "ok":
            kind, detail = "no_answer", p.error
        elif p.intent != t.expected_intent:
            kind, detail = "wrong_intent", p.reasoning
        elif _norm_ref(p.order_ref) != _norm_ref(t.expected_order_ref):
            kind, detail = "wrong_order_ref", p.reasoning
        else:
            continue
        errors.append(
            ErrorCase(
                ticket_id=p.ticket_id,
                rep=p.rep,
                kind=kind,
                text=t.text,
                expected_intent=t.expected_intent,
                predicted_intent=p.intent,
                expected_order_ref=t.expected_order_ref,
                predicted_order_ref=p.order_ref,
                confidence=p.confidence,
                detail=detail,
            )
        )

    tokens = [p.input_tokens + p.output_tokens for p in predictions]
    total_cost = sum((p.cost_usd for p in predictions), Decimal("0"))
    latencies = [p.latency_ms for p in ok if p.latency_ms is not None]

    return EvalMetrics(
        n_rows=len(predictions),
        n_ok=n_ok,
        n_no_answer=len(predictions) - n_ok,
        accuracy_strict=strict / n_ok if n_ok else 0.0,
        accuracy_strict_ci=wilson_interval(strict, n_ok),
        accuracy_lenient=lenient / n_ok if n_ok else 0.0,
        accuracy_lenient_ci=wilson_interval(lenient, n_ok),
        majority_baseline=majority_count / len(tickets),
        majority_intent=majority_intent,
        order_ref_accuracy=refs_ok / n_ok if n_ok else 0.0,
        per_rep_accuracy=[sum(v) / len(v) for _, v in sorted(per_rep.items())],
        per_class=per_class,
        confusion=confusion,
        calibration=calibration,
        expected_calibration_error=ece_sum / n_ok if n_ok else None,
        errors=errors,
        total_input_tokens=sum(p.input_tokens for p in predictions),
        total_output_tokens=sum(p.output_tokens for p in predictions),
        total_cost_usd=total_cost,
        cost_per_row_usd=total_cost / len(predictions) if predictions else Decimal("0"),
        tokens_per_row=(min(tokens), statistics.median(tokens), max(tokens))
        if tokens
        else (0, 0.0, 0),
        latency_ms_p50=_percentile(latencies, 0.5),
        latency_ms_p95=_percentile(latencies, 0.95),
    )
