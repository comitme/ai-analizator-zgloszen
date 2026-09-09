"""Application configuration.

Two sources, deliberately separate:

* ``config/app.yaml``          - technical knobs (models, thresholds, FX rate)
* ``config/return_policy.yaml``- business rules, loaded by ``policy.loader``

Secrets never live in YAML; they come from the environment (``.env``).
Everything is validated at import time so a typo fails at startup, not on the
first customer ticket.
"""

import os
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


class ModelsConfig(BaseModel):
    classification: str
    generation: str
    classification_max_tokens: int = Field(gt=0)
    generation_max_tokens: int = Field(gt=0)


class TriageConfig(BaseModel):
    confidence_threshold: float = Field(ge=0.0, le=1.0)


class CostConfig(BaseModel):
    usd_to_pln: Decimal = Field(gt=0)


class AppConfig(BaseModel):
    models: ModelsConfig
    triage: TriageConfig
    cost: CostConfig

    # --- Environment-sourced settings ---

    @property
    def database_url(self) -> str:
        return os.getenv("DATABASE_URL", f"sqlite:///{PROJECT_ROOT / 'data' / 'triage.db'}")

    @property
    def use_fake_llm(self) -> bool:
        """Offline mode: run the whole pipeline with a stub classifier, no API key, no cost."""
        return os.getenv("TRIAGE_FAKE_LLM", "0").lower() in {"1", "true", "yes"}


def load_app_config(path: Path | None = None) -> AppConfig:
    """Read and validate ``app.yaml``. Raises on malformed config."""
    path = path or CONFIG_DIR / "app.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return AppConfig.model_validate(raw)


@lru_cache(maxsize=1)
def get_app_config() -> AppConfig:
    """Cached accessor used by the API dependency layer."""
    return load_app_config()
