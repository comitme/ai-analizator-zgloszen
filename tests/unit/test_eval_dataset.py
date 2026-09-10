"""Integrity checks on the evaluation dataset itself.

A wrong label or a dangling order reference caps measurable accuracy for reasons that
have nothing to do with the model, so the dataset gets tests like code does.
"""

from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from ticket_triage.domain.enums import Intent
from ticket_triage.evaluation.dataset import EvalTicket, load_dataset
from ticket_triage.llm.prompts import CLASSIFICATION_SYSTEM, CLASSIFICATION_USER_TEMPLATE

DATASET_DIR = Path(__file__).resolve().parents[2] / "eval" / "dataset"


@pytest.fixture(scope="module")
def dataset():
    return load_dataset(DATASET_DIR)


def test_size_is_within_the_planned_range(dataset):
    assert 30 <= len(dataset.tickets) <= 50


def test_every_intent_has_enough_examples(dataset):
    counts = Counter(t.expected_intent for t in dataset.tickets)
    assert {i: counts[i] for i in Intent if counts[i] < 5} == {}


def test_no_class_dominates(dataset):
    """A majority-class baseline near the model's score would make accuracy meaningless."""
    top = Counter(t.expected_intent for t in dataset.tickets).most_common(1)[0][1]
    assert top / len(dataset.tickets) <= 0.3


def test_order_references_resolve_unless_deliberately_unknown(dataset):
    dangling = [
        t.id
        for t in dataset.tickets
        if t.expected_order_ref
        and t.expected_order_ref not in dataset.orders
        and "unknown_order_ref" not in t.tags
    ]
    assert dangling == []


def test_unknown_order_ref_cases_really_are_unknown(dataset):
    for t in dataset.tickets:
        if "unknown_order_ref" in t.tags:
            assert t.expected_order_ref and t.expected_order_ref not in dataset.orders


def test_order_ref_label_appears_in_the_text(dataset):
    """The model is told to copy the number only when the customer wrote it."""
    for t in dataset.tickets:
        if t.expected_order_ref:
            assert t.expected_order_ref in t.text, t.id


def test_ambiguous_tag_matches_acceptable_intents(dataset):
    for t in dataset.tickets:
        assert ("ambiguous" in t.tags) == t.ambiguous, t.id


def test_hard_cases_are_represented(dataset):
    tags = Counter(tag for t in dataset.tickets for tag in t.tags)
    for required in (
        "typos",
        "no_diacritics",
        "injection",
        "no_order_ref",
        "ambiguous",
        "angry",
        "legal",
    ):
        assert tags[required] >= 1, required


def test_no_label_leakage_into_the_prompt(dataset):
    prompt = CLASSIFICATION_SYSTEM + CLASSIFICATION_USER_TEMPLATE
    assert [t.id for t in dataset.tickets if t.text in prompt] == []


def test_provenance_is_recorded(dataset):
    assert "model" in dataset.meta.ground_truth_source.lower()


def test_acceptable_intents_must_include_expected():
    with pytest.raises(ValidationError):
        EvalTicket(
            id="x",
            text="t",
            expected_intent=Intent.OTHER,
            acceptable_intents=[Intent.SHIPPING_STATUS],
        )


def test_duplicate_ids_are_rejected(tmp_path):
    (tmp_path / "meta.json").write_text(
        '{"version": 1, "eval_date": "2026-09-10", "ground_truth_source": "model"}',
        encoding="utf-8",
    )
    (tmp_path / "orders.json").write_text("[]", encoding="utf-8")
    line = '{"id": "t1", "text": "a", "expected_intent": "other"}\n'
    (tmp_path / "tickets.jsonl").write_text(line * 2, encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        load_dataset(tmp_path)
