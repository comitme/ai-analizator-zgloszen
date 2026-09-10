"""Tests for the confidence-threshold sweep.

Uses the policy fixture from conftest, not config/return_policy.yaml, so tuning the
shop's real rules cannot break these tests.
"""

from pathlib import Path

from ticket_triage.domain.enums import Intent
from ticket_triage.evaluation.dataset import EvalTicket, load_dataset
from ticket_triage.evaluation.predictions import OracleClassifier, Prediction, run_predictions
from ticket_triage.evaluation.sweep import sweep

from ..conftest import TODAY

DATASET_DIR = Path(__file__).resolve().parents[2] / "eval" / "dataset"


def _ticket(id_, intent=Intent.RETURN_NO_REASON, ref="10432", text="Chcę zwrócić buty."):
    return EvalTicket(id=id_, text=text, expected_intent=intent, expected_order_ref=ref)


def _pred(id_, intent, conf, ref="10432", status="ok"):
    return Prediction(
        ticket_id=id_,
        status=status,
        intent=intent if status == "ok" else None,
        order_ref=ref,
        confidence=conf if status == "ok" else None,
        reasoning="",
    )


def test_oracle_has_no_wrong_automatic_replies_at_any_threshold(engine):
    dataset = load_dataset(DATASET_DIR)
    predictions = run_predictions(OracleClassifier(dataset.tickets), dataset.tickets, workers=1)
    result = sweep(
        dataset.tickets, predictions, dataset.orders, engine, today=dataset.meta.eval_date
    )

    assert all(r.auto_wrong == 0 for r in result.rows)
    # Oracle confidence is 1.0, so the threshold never bites: automation equals the ceiling.
    assert {round(r.automation_rate, 6) for r in result.rows} == {
        round(result.automation_ceiling, 6)
    }


def test_hard_rules_cap_automation_below_one(engine):
    dataset = load_dataset(DATASET_DIR)
    predictions = run_predictions(OracleClassifier(dataset.tickets), dataset.tickets, workers=1)
    result = sweep(
        dataset.tickets, predictions, dataset.orders, engine, today=dataset.meta.eval_date
    )
    assert 0.0 < result.automation_ceiling < 1.0


def test_automation_never_increases_with_the_threshold(engine, order_factory):
    tickets = [_ticket(str(i)) for i in range(5)]
    predictions = [
        _pred(str(i), Intent.RETURN_NO_REASON, conf)
        for i, conf in enumerate([0.2, 0.5, 0.7, 0.8, 0.99])
    ]
    result = sweep(tickets, predictions, {"10432": order_factory(days_ago=3)}, engine, today=TODAY)
    rates = [r.automation_rate for r in result.rows]
    assert rates == sorted(rates, reverse=True)


def test_confident_wrong_intent_is_counted_as_a_wrong_automatic_reply(engine, order_factory):
    tickets = [_ticket("a")]
    predictions = [_pred("a", Intent.SHIPPING_STATUS, 0.9)]
    result = sweep(
        tickets,
        predictions,
        {"10432": order_factory(days_ago=3)},
        engine,
        today=TODAY,
        thresholds=[0.5, 0.95],
    )
    low, high = result.rows
    assert (low.auto, low.auto_wrong) == (1, 1)
    assert (high.auto, high.auto_wrong) == (0, 0)


def test_wrong_order_ref_resolving_to_another_order_is_wrong(engine, order_factory):
    orders = {
        "10432": order_factory(days_ago=3),
        "10433": order_factory(days_ago=4, order_ref="10433"),
    }
    result = sweep(
        [_ticket("a")],
        [_pred("a", Intent.RETURN_NO_REASON, 0.9, ref="10433")],
        orders,
        engine,
        today=TODAY,
        thresholds=[0.5],
    )
    assert result.rows[0].auto_wrong == 1


def test_no_answer_is_never_automated(engine, order_factory):
    result = sweep(
        [_ticket("a")],
        [_pred("a", None, None, status="error")],
        {"10432": order_factory()},
        engine,
        today=TODAY,
        thresholds=[0.0],
    )
    assert result.rows[0].auto == 0


def test_recommends_most_automation_within_the_error_budget(engine, order_factory):
    orders = {"10432": order_factory(days_ago=3)}
    tickets = [_ticket("ok1"), _ticket("ok2"), _ticket("bad")]
    predictions = [
        _pred("ok1", Intent.RETURN_NO_REASON, 0.95),
        _pred("ok2", Intent.RETURN_NO_REASON, 0.9),
        _pred("bad", Intent.SHIPPING_STATUS, 0.6),  # wrong, but only automated at low thresholds
    ]
    result = sweep(tickets, predictions, orders, engine, today=TODAY, thresholds=[0.5, 0.7, 0.92])
    assert result.recommended_threshold == 0.7


def test_no_recommendation_when_every_threshold_breaks_the_budget(engine, order_factory):
    result = sweep(
        [_ticket("bad")],
        [_pred("bad", Intent.SHIPPING_STATUS, 0.99)],
        {"10432": order_factory()},
        engine,
        today=TODAY,
        thresholds=[0.5, 0.9],
    )
    assert result.recommended_threshold is None
