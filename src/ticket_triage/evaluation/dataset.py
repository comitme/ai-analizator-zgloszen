"""Evaluation dataset: labelled tickets, the orders they refer to, and provenance.

Kept in the package (not only in ``eval/``) so the loading and validation rules are
unit-tested like any other code - a mislabelled or malformed case silently caps the
accuracy we can measure.
"""

import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from ..domain.enums import Intent
from ..domain.models import Order


class EvalTicket(BaseModel):
    """One labelled customer message."""

    id: str
    text: str = Field(min_length=1)
    expected_intent: Intent
    acceptable_intents: list[Intent] = Field(
        default_factory=list,
        description=(
            "Every intent a careful human would accept. Defaults to [expected_intent]. "
            "More than one entry marks a genuinely ambiguous case, scored twice: strict "
            "(expected only) and lenient (any acceptable)."
        ),
    )
    expected_order_ref: str | None = None
    tags: list[str] = Field(default_factory=list)
    note: str | None = None

    @model_validator(mode="after")
    def _acceptable_includes_expected(self) -> "EvalTicket":
        if not self.acceptable_intents:
            self.acceptable_intents = [self.expected_intent]
        elif self.expected_intent not in self.acceptable_intents:
            raise ValueError(f"{self.id}: expected_intent missing from acceptable_intents")
        return self

    @property
    def ambiguous(self) -> bool:
        return len(self.acceptable_intents) > 1


class EvalMeta(BaseModel):
    version: int
    eval_date: date = Field(
        description="Fixed 'today' for policy evaluation, so results never drift with the clock."
    )
    ground_truth_source: str


class EvalDataset(BaseModel):
    meta: EvalMeta
    tickets: list[EvalTicket]
    orders: dict[str, Order]


def load_dataset(dataset_dir: Path) -> EvalDataset:
    """Load and validate ``meta.json``, ``tickets.jsonl`` and ``orders.json``."""
    meta = EvalMeta.model_validate_json((dataset_dir / "meta.json").read_text(encoding="utf-8"))

    tickets = [
        EvalTicket.model_validate_json(line)
        for line in (dataset_dir / "tickets.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [t.id for t in tickets]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"Duplicate ticket ids: {duplicates}")

    raw_orders = json.loads((dataset_dir / "orders.json").read_text(encoding="utf-8"))
    orders = {o["order_ref"]: Order.model_validate(o) for o in raw_orders}

    # Sorted for deterministic iteration order - reports and sweeps must not reorder.
    return EvalDataset(meta=meta, tickets=sorted(tickets, key=lambda t: t.id), orders=orders)
