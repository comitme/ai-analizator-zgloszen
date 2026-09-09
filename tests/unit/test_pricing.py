"""Tests for cost accounting.

Cost appears in the README as a selling point, so the arithmetic behind it has to be
right - and it has to stay right when someone edits the pricing table.
"""

from decimal import Decimal

import pytest

from ticket_triage.llm.pricing import (
    MODEL_PRICING,
    UnknownModelError,
    build_usage_record,
    cost_usd,
)


def test_sonnet_pricing_is_exact():
    """1M in + 1M out on Sonnet 5 = $2 + $10."""
    assert cost_usd("claude-sonnet-5", input_tokens=1_000_000, output_tokens=1_000_000) == Decimal(
        "12.00"
    )


def test_realistic_single_ticket_cost():
    """A classification call: ~600 in, ~120 out."""
    cost = cost_usd("claude-sonnet-5", input_tokens=600, output_tokens=120)
    # 600 * 2/1M + 120 * 10/1M = 0.0012 + 0.0012
    assert cost == Decimal("0.0024")


def test_haiku_is_cheaper_than_sonnet_for_the_same_work():
    """The premise of the model-comparison section in the evaluation."""
    args = {"input_tokens": 600, "output_tokens": 120}
    assert cost_usd("claude-haiku-4-5", **args) < cost_usd("claude-sonnet-5", **args)


def test_cache_reads_are_an_order_of_magnitude_cheaper():
    cached = cost_usd("claude-sonnet-5", cache_read_tokens=1_000_000)
    fresh = cost_usd("claude-sonnet-5", input_tokens=1_000_000)
    assert cached == fresh / 10


def test_cache_writes_cost_a_premium():
    written = cost_usd("claude-sonnet-5", cache_write_tokens=1_000_000)
    fresh = cost_usd("claude-sonnet-5", input_tokens=1_000_000)
    assert written == fresh * Decimal("1.25")


def test_unknown_model_raises_instead_of_reporting_zero():
    """Silently costing 0.00 would make the metrics dashboard lie."""
    with pytest.raises(UnknownModelError, match="No pricing for model"):
        cost_usd("gpt-imaginary", input_tokens=100)


def test_usage_record_converts_to_pln():
    record = build_usage_record(
        "claude-sonnet-5",
        input_tokens=1_000_000,
        output_tokens=0,
        usd_to_pln=Decimal("4.05"),
    )
    assert record.cost_usd == Decimal("2.00")
    assert record.cost_pln == Decimal("8.10")


def test_usage_records_sum():
    a = build_usage_record(
        "claude-sonnet-5", input_tokens=100, output_tokens=50, usd_to_pln=Decimal("4")
    )
    b = build_usage_record(
        "claude-sonnet-5", input_tokens=200, output_tokens=25, usd_to_pln=Decimal("4")
    )
    total = a + b
    assert total.input_tokens == 300
    assert total.output_tokens == 75
    assert total.cost_usd == a.cost_usd + b.cost_usd
    assert total.model == "claude-sonnet-5"


def test_mixed_model_sum_keeps_both_labels():
    a = build_usage_record("claude-haiku-4-5", input_tokens=100, usd_to_pln=Decimal("4"))
    b = build_usage_record("claude-sonnet-5", input_tokens=100, usd_to_pln=Decimal("4"))
    assert (a + b).model == "claude-haiku-4-5+claude-sonnet-5"


@pytest.mark.parametrize("model", sorted(MODEL_PRICING))
def test_every_priced_model_has_output_dearer_than_input(model):
    """Sanity check on the table itself - output always costs more than input."""
    pricing = MODEL_PRICING[model]
    assert pricing.output_per_mtok > pricing.input_per_mtok > 0
