"""Shared fixtures.

Nothing here touches the network. The default test run (`make test`) never calls
Anthropic and never needs an API key - tests you have to pay for are tests you stop
running.
"""

from datetime import date
from decimal import Decimal

import pytest

from ticket_triage.domain.models import Order
from ticket_triage.policy.engine import PolicyEngine
from ticket_triage.policy.loader import EscalationRules, ReturnPolicy

TODAY = date(2026, 9, 9)


@pytest.fixture
def policy() -> ReturnPolicy:
    """A policy fixed in the test file, not read from config/.

    Tests must not break because someone tuned the shop's real YAML.
    """
    return ReturnPolicy(
        shop_name="Sklep Testowy",
        return_window_days=14,
        excluded_categories=frozenset({"bielizna", "kosmetyki"}),
        warranty_months=24,
        escalation=EscalationRules(
            amount_above_pln=Decimal("2000"),
            keywords=("uokik", "sąd", "prawnik", "rzecznik konsumentów"),
        ),
    )


@pytest.fixture
def engine(policy: ReturnPolicy) -> PolicyEngine:
    return PolicyEngine(policy)


@pytest.fixture
def order_factory():
    """Build an order relative to the frozen `TODAY`, so tests never depend on the clock."""

    def _make(
        *,
        days_ago: int = 3,
        category: str = "obuwie",
        amount_pln: str = "249.00",
        order_ref: str = "10432",
    ) -> Order:
        return Order(
            order_ref=order_ref,
            purchase_date=date.fromordinal(TODAY.toordinal() - days_ago),
            category=category,
            amount_pln=Decimal(amount_pln),
        )

    return _make
