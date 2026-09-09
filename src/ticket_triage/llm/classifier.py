"""Ticket classification via Claude's structured outputs.

``client.messages.parse(output_format=Classification)`` constrains the response to
the Pydantic schema and hands back a validated instance. No regex, no JSON repair,
no "the model wrapped it in a code fence again" branch.
"""

from decimal import Decimal
from typing import Protocol

import anthropic

from ..domain.models import Classification, UsageRecord
from .pricing import build_usage_record
from .prompts import CLASSIFICATION_SYSTEM, build_classification_messages


class Classifier(Protocol):
    """Anything that can turn ticket text into a classification plus its cost."""

    def classify(self, ticket_text: str) -> tuple[Classification, UsageRecord]:
        ...


class AnthropicClassifier:
    """Production classifier. One API call per ticket."""

    def __init__(
        self,
        client: anthropic.Anthropic,
        *,
        model: str,
        max_tokens: int,
        usd_to_pln: Decimal,
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._usd_to_pln = usd_to_pln

    def classify(self, ticket_text: str) -> tuple[Classification, UsageRecord]:
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=self._max_tokens,
            system=CLASSIFICATION_SYSTEM,
            messages=build_classification_messages(ticket_text),
            output_format=Classification,
        )

        usage = build_usage_record(
            self._model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
            usd_to_pln=self._usd_to_pln,
        )
        return response.parsed_output, usage
