"""Dependency wiring.

One place decides which concrete implementations the request handlers get. That is
what makes the classifier swappable for a stub in tests (``app.dependency_overrides``)
and what makes ``TRIAGE_FAKE_LLM=1`` a one-line switch rather than a code change.
"""

from functools import lru_cache

import anthropic

from ..config import AppConfig, get_app_config
from ..llm.classifier import AnthropicClassifier, Classifier
from ..llm.fake import FakeClassifier
from ..policy.engine import PolicyEngine
from ..policy.loader import get_return_policy


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return get_app_config()


@lru_cache(maxsize=1)
def get_policy_engine() -> PolicyEngine:
    """Compiled once - keyword regexes are built at construction time."""
    return PolicyEngine(get_return_policy())


@lru_cache(maxsize=1)
def get_classifier() -> Classifier:
    config = get_config()
    if config.use_fake_llm:
        return FakeClassifier(usd_to_pln=config.cost.usd_to_pln)
    return AnthropicClassifier(
        anthropic.Anthropic(),
        model=config.models.classification,
        max_tokens=config.models.classification_max_tokens,
        usd_to_pln=config.cost.usd_to_pln,
    )
