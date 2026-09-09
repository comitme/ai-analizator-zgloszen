"""Dependency wiring.

One place decides which concrete implementations the request handlers get. That is
what makes the classifier and responder swappable for stubs in tests
(``app.dependency_overrides``) and what makes ``TRIAGE_FAKE_LLM=1`` a one-line switch
rather than a code change.
"""

from functools import lru_cache

import anthropic

from ..config import AppConfig, get_app_config
from ..llm.classifier import AnthropicClassifier, Classifier
from ..llm.fake import FakeClassifier, FakeResponder
from ..llm.responder import AnthropicResponder, Responder
from ..policy.engine import PolicyEngine
from ..policy.loader import get_return_policy
from ..triage.decision import DecisionEngine
from ..triage.service import TriageService


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return get_app_config()


@lru_cache(maxsize=1)
def get_policy_engine() -> PolicyEngine:
    """Compiled once - keyword regexes are built at construction time."""
    return PolicyEngine(get_return_policy())


@lru_cache(maxsize=1)
def get_decision_engine() -> DecisionEngine:
    return DecisionEngine(get_config().triage.confidence_threshold)


@lru_cache(maxsize=1)
def get_anthropic_client() -> anthropic.Anthropic:
    """One HTTP client shared by both model-facing components.

    Separated so the classifier and the responder do not each open their own
    connection pool for the same host.
    """
    return anthropic.Anthropic()


@lru_cache(maxsize=1)
def get_classifier() -> Classifier:
    config = get_config()
    if config.use_fake_llm:
        return FakeClassifier(usd_to_pln=config.cost.usd_to_pln)
    return AnthropicClassifier(
        get_anthropic_client(),
        model=config.models.classification,
        max_tokens=config.models.classification_max_tokens,
        usd_to_pln=config.cost.usd_to_pln,
    )


@lru_cache(maxsize=1)
def get_responder() -> Responder:
    config = get_config()
    if config.use_fake_llm:
        return FakeResponder()
    return AnthropicResponder(
        get_anthropic_client(),
        model=config.models.generation,
        max_tokens=config.models.generation_max_tokens,
        usd_to_pln=config.cost.usd_to_pln,
    )


@lru_cache(maxsize=1)
def get_triage_service() -> TriageService:
    return TriageService(
        policy_engine=get_policy_engine(),
        decision_engine=get_decision_engine(),
        responder=get_responder(),
    )
