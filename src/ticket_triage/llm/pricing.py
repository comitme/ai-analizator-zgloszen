"""Token pricing and cost accounting.

Cost is a first-class output of this system, not an afterthought. Every model call
produces a :class:`UsageRecord`; the metrics view sums them. That is what lets the
README answer "what does this cost at 10 000 tickets a month" with a measured
number instead of a guess.

Prices are USD per 1 000 000 tokens, from Anthropic's published pricing.
Cache multipliers follow the documented rates: writes ~1.25x the input rate,
reads ~0.1x.
"""

from dataclasses import dataclass
from decimal import Decimal

from ..domain.models import UsageRecord

_CACHE_WRITE_MULTIPLIER = Decimal("1.25")
_CACHE_READ_MULTIPLIER = Decimal("0.10")


@dataclass(frozen=True)
class ModelPricing:
    """USD per 1M tokens."""

    input_per_mtok: Decimal
    output_per_mtok: Decimal

    @property
    def cache_write_per_mtok(self) -> Decimal:
        return self.input_per_mtok * _CACHE_WRITE_MULTIPLIER

    @property
    def cache_read_per_mtok(self) -> Decimal:
        return self.input_per_mtok * _CACHE_READ_MULTIPLIER


MODEL_PRICING: dict[str, ModelPricing] = {
    "claude-opus-5": ModelPricing(Decimal("5.00"), Decimal("25.00")),
    "claude-sonnet-5": ModelPricing(Decimal("2.00"), Decimal("10.00")),
    "claude-haiku-4-5": ModelPricing(Decimal("1.00"), Decimal("5.00")),
}

_MILLION = Decimal("1000000")


class UnknownModelError(KeyError):
    """Raised when a model has no pricing entry.

    Deliberately fatal rather than defaulting to zero: silently reporting a cost of
    0.00 would be worse than crashing, because it would make the metrics lie.
    """


def get_pricing(model: str) -> ModelPricing:
    try:
        return MODEL_PRICING[model]
    except KeyError as exc:
        known = ", ".join(sorted(MODEL_PRICING))
        raise UnknownModelError(
            f"No pricing for model {model!r}. Add it to MODEL_PRICING. Known: {known}"
        ) from exc


def cost_usd(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Decimal:
    """Exact cost of one call in USD, using Decimal throughout (no float drift)."""
    p = get_pricing(model)
    return (
        Decimal(input_tokens) * p.input_per_mtok
        + Decimal(output_tokens) * p.output_per_mtok
        + Decimal(cache_read_tokens) * p.cache_read_per_mtok
        + Decimal(cache_write_tokens) * p.cache_write_per_mtok
    ) / _MILLION


def build_usage_record(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    usd_to_pln: Decimal,
) -> UsageRecord:
    """Assemble a :class:`UsageRecord` with both currencies filled in."""
    usd = cost_usd(
        model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
    )
    return UsageRecord(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        cost_usd=usd,
        cost_pln=usd * usd_to_pln,
    )
