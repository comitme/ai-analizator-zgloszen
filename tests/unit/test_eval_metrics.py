"""Tests for evaluation metrics and the harness itself (oracle + null baseline)."""

from decimal import Decimal
from pathlib import Path

import pytest

from ticket_triage.domain.enums import Intent
from ticket_triage.evaluation.dataset import EvalTicket, load_dataset
from ticket_triage.evaluation.metrics import evaluate, wilson_interval
from ticket_triage.evaluation.predictions import OracleClassifier, Prediction, run_predictions

DATASET_DIR = Path(__file__).resolve().parents[2] / "eval" / "dataset"


def ticket(id_, intent, *, ref=None, acceptable=None):
    return EvalTicket(
        id=id_,
        text=f"text {id_}",
        expected_intent=intent,
        expected_order_ref=ref,
        acceptable_intents=acceptable or [],
    )


def pred(id_, intent, *, ref=None, conf=0.9, status="ok", cost="0.001", rep=0):
    return Prediction(
        ticket_id=id_,
        rep=rep,
        status=status,
        intent=intent if status == "ok" else None,
        order_ref=ref,
        confidence=conf if status == "ok" else None,
        input_tokens=500,
        output_tokens=100,
        cost_usd=Decimal(cost),
    )


class TestWilson:
    def test_empty(self):
        assert wilson_interval(0, 0) == (0.0, 0.0)

    def test_perfect_score_is_not_certain_at_small_n(self):
        """40/40 still has a lower bound well under 100% - the point of reporting it."""
        lo, hi = wilson_interval(40, 40)
        assert hi == pytest.approx(1.0)
        assert 0.90 < lo < 0.93

    def test_bounds_stay_in_unit_interval(self):
        lo, hi = wilson_interval(0, 5)
        assert lo == 0.0 and 0 < hi < 1


class TestHarness:
    def test_oracle_scores_perfectly_on_the_real_dataset(self):
        """If this fails, the eval pipeline is broken - not the model."""
        dataset = load_dataset(DATASET_DIR)
        predictions = run_predictions(OracleClassifier(dataset.tickets), dataset.tickets, workers=1)
        m = evaluate(dataset.tickets, predictions)
        assert m.accuracy_strict == 1.0
        assert m.order_ref_accuracy == 1.0
        assert m.errors == []
        assert m.expected_calibration_error == pytest.approx(0.0)

    def test_majority_class_baseline_is_well_below_perfect(self):
        dataset = load_dataset(DATASET_DIR)
        m = evaluate(
            dataset.tickets,
            [
                pred(t.id, Intent.RETURN_NO_REASON, ref=t.expected_order_ref)
                for t in dataset.tickets
            ],
        )
        assert m.accuracy_strict == pytest.approx(m.majority_baseline)
        assert m.majority_baseline < 0.3


class TestScoring:
    def test_no_answer_is_not_a_wrong_answer(self):
        tickets = [ticket("a", Intent.OTHER), ticket("b", Intent.OTHER)]
        m = evaluate(tickets, [pred("a", Intent.OTHER), pred("b", None, status="error")])
        assert m.n_ok == 1 and m.n_no_answer == 1
        assert m.accuracy_strict == 1.0
        assert [e.kind for e in m.errors] == ["no_answer"]

    def test_lenient_accepts_alternatives_strict_does_not(self):
        tickets = [
            ticket(
                "a",
                Intent.REFUND_STATUS,
                acceptable=[Intent.REFUND_STATUS, Intent.RETURN_NO_REASON],
            )
        ]
        m = evaluate(tickets, [pred("a", Intent.RETURN_NO_REASON)])
        assert m.accuracy_strict == 0.0
        assert m.accuracy_lenient == 1.0

    def test_wrong_order_ref_is_its_own_error_kind(self):
        tickets = [ticket("a", Intent.SHIPPING_STATUS, ref="20001")]
        m = evaluate(tickets, [pred("a", Intent.SHIPPING_STATUS, ref="20002")])
        assert m.accuracy_strict == 1.0
        assert m.order_ref_accuracy == 0.0
        assert [e.kind for e in m.errors] == ["wrong_order_ref"]

    def test_whitespace_in_order_ref_is_normalised(self):
        tickets = [ticket("a", Intent.SHIPPING_STATUS, ref="20001")]
        assert (
            evaluate(tickets, [pred("a", Intent.SHIPPING_STATUS, ref=" 20001 ")]).order_ref_accuracy
            == 1.0
        )

    def test_per_class_precision_and_recall(self):
        tickets = [
            ticket("a", Intent.OTHER),
            ticket("b", Intent.OTHER),
            ticket("c", Intent.SHIPPING_STATUS),
        ]
        m = evaluate(
            tickets,
            [
                pred("a", Intent.OTHER),
                pred("b", Intent.SHIPPING_STATUS),
                pred("c", Intent.SHIPPING_STATUS),
            ],
        )
        by = {c.intent: c for c in m.per_class}
        assert by[Intent.OTHER].precision == 1.0 and by[Intent.OTHER].recall == 0.5
        assert (
            by[Intent.SHIPPING_STATUS].precision == 0.5 and by[Intent.SHIPPING_STATUS].recall == 1.0
        )
        assert m.confusion["other"]["shipping_status"] == 1

    def test_overconfident_mistakes_show_up_in_calibration(self):
        tickets = [ticket(str(i), Intent.OTHER) for i in range(4)]
        predictions = [pred(str(i), Intent.SHIPPING_STATUS, conf=0.95) for i in range(4)]
        m = evaluate(tickets, predictions)
        top = m.calibration[-1]
        assert top.n == 4 and top.accuracy == 0.0
        assert m.expected_calibration_error == pytest.approx(0.95)

    def test_cost_and_tokens_are_summed_from_rows(self):
        tickets = [ticket("a", Intent.OTHER), ticket("b", Intent.OTHER)]
        m = evaluate(
            tickets, [pred("a", Intent.OTHER, cost="0.002"), pred("b", Intent.OTHER, cost="0.003")]
        )
        assert m.total_cost_usd == Decimal("0.005")
        assert m.total_input_tokens == 1000
        assert m.tokens_per_row == (600, 600, 600)

    def test_repetitions_are_reported_separately(self):
        tickets = [ticket("a", Intent.OTHER)]
        m = evaluate(
            tickets, [pred("a", Intent.OTHER, rep=0), pred("a", Intent.SHIPPING_STATUS, rep=1)]
        )
        assert m.per_rep_accuracy == [1.0, 0.0]
