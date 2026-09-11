"""Formatting helpers for the panel.

Small, but they sit between JSON and the operator's screen, and the API sends
Decimals as JSON strings - formatting one with ``f"{value:.4f}"`` raises. These pin
that contract so the panel cannot crash on a money field again.
"""

from ui.common import confidence_badge, money, percent, stub_share


class TestMoney:
    def test_formats_a_decimal_string_from_json(self):
        """Pydantic serialises Decimal as a string; this must not raise."""
        assert money("0.006300") == "$0.0063"

    def test_formats_a_plain_number(self):
        assert money(0.0063) == "$0.0063"

    def test_currency_and_precision_are_selectable(self):
        assert money("0.0158", currency="zł", places=4) == "0.0158 zł"

    def test_unparsable_value_becomes_a_dash_rather_than_an_error(self):
        assert money(None) == "—"
        assert money("brak") == "—"


class TestPercent:
    def test_none_is_not_shown_as_zero(self):
        """'0%' would claim the system automates nothing; None means we do not know."""
        assert percent(None) == "brak danych"

    def test_fraction_becomes_a_percentage(self):
        assert percent(0.625) == "62.5%"


class TestConfidenceBadge:
    def test_high_confidence_is_green(self):
        assert confidence_badge(0.95).startswith("🟢")

    def test_below_threshold_is_red(self):
        assert confidence_badge(0.4).startswith("🔴")

    def test_missing_confidence_is_a_dash(self):
        assert confidence_badge(None) == "—"


class TestStubDetection:
    """The panel must say when a cost projection rests on stub rows.

    The offline stub records real tickets with a cost of exactly zero, so a mixed
    database silently produces an optimistic projection - which is how a shop owner
    ends up believing the system is free.
    """

    def test_no_stub_calls_means_nothing_to_warn_about(self):
        assert stub_share({"claude-sonnet-5": 40}) is None

    def test_all_stub_calls_is_reported_as_everything(self):
        assert stub_share({"fake": 24}) == 1.0

    def test_mixed_data_reports_the_stub_share(self):
        assert stub_share({"fake": 6, "claude-sonnet-5": 14}) == 0.3

    def test_empty_metrics_are_not_a_warning(self):
        assert stub_share({}) is None
