"""Loading and validation of ``config/return_policy.yaml``.

The loaded policy is frozen: the engine must not be able to mutate the rules it
is evaluating.
"""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config import CONFIG_DIR


class EscalationRules(BaseModel):
    model_config = ConfigDict(frozen=True)

    amount_above_pln: Decimal = Field(gt=0)
    keywords: tuple[str, ...] = ()

    @field_validator("keywords", mode="before")
    @classmethod
    def _normalise(cls, value: object) -> object:
        """Lowercase and strip once at load time so matching stays cheap."""
        if isinstance(value, list):
            return tuple(str(k).strip().lower() for k in value if str(k).strip())
        return value


class ReturnPolicy(BaseModel):
    """The shop's rules. One instance per shop - this is the multi-tenant seam."""

    model_config = ConfigDict(frozen=True)

    shop_name: str
    return_window_days: int = Field(ge=0)
    excluded_categories: frozenset[str] = frozenset()
    warranty_months: int = Field(ge=0)
    escalation: EscalationRules

    @field_validator("excluded_categories", mode="before")
    @classmethod
    def _normalise(cls, value: object) -> object:
        if isinstance(value, list):
            return frozenset(str(c).strip().lower() for c in value if str(c).strip())
        return value


def load_return_policy(path: Path | None = None) -> ReturnPolicy:
    """Read and validate the policy file. Raises on malformed config."""
    path = path or CONFIG_DIR / "return_policy.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return ReturnPolicy.model_validate(raw)


@lru_cache(maxsize=1)
def get_return_policy() -> ReturnPolicy:
    """Cached accessor used by the API dependency layer."""
    return load_return_policy()
