"""Drafting the Polish reply.

The second - and last - place a model is called. It receives the policy verdict as
an established fact and phrases it; it never decides eligibility. That separation is
what lets the reply be reviewed for tone rather than for correctness.

Plain ``messages.create`` here rather than the classifier's ``parse``: the output is
prose, and wrapping prose in JSON would spend tokens on escaping newlines for no
gain. The "no preamble, reply only" guarantee comes from the system prompt instead.
"""

from decimal import Decimal
from typing import Protocol

import anthropic

from ..domain.enums import INTENT_LABELS_PL
from ..domain.models import Classification, Order, PolicyResult, UsageRecord
from .pricing import build_usage_record
from .prompts import RESPONSE_SYSTEM, build_response_messages


class Responder(Protocol):
    """Anything that can draft a customer reply from an already-decided verdict."""

    def generate(
        self,
        *,
        ticket_text: str,
        classification: Classification,
        order: Order | None,
        policy: PolicyResult,
    ) -> tuple[str, UsageRecord]: ...


class AnthropicResponder:
    """Production responder. One API call per auto-answered ticket."""

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

    def generate(
        self,
        *,
        ticket_text: str,
        classification: Classification,
        order: Order | None,
        policy: PolicyResult,
    ) -> tuple[str, UsageRecord]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=RESPONSE_SYSTEM,
            messages=build_response_messages(
                ticket_text=ticket_text,
                intent_label=INTENT_LABELS_PL[classification.intent],
                outcome=policy.outcome.value,
                reason=policy.reason_pl,
                order_ref=order.order_ref if order else None,
                purchase_date=order.purchase_date.isoformat() if order else None,
                category=order.category if order else None,
                amount=f"{order.amount_pln:.2f}" if order else None,
            ),
        )

        # Filter on block type: on thinking-capable models the response can carry
        # thinking blocks alongside the text, and `.text` only exists on text blocks.
        reply = "".join(b.text for b in response.content if b.type == "text").strip()
        if not reply:
            raise EmptyReplyError(f"Model returned no text (stop_reason={response.stop_reason!r})")

        usage = build_usage_record(
            self._model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
            usd_to_pln=self._usd_to_pln,
        )
        return reply, usage


class EmptyReplyError(RuntimeError):
    """The model returned no usable text.

    Raised rather than returning an empty string so the caller degrades the ticket to
    a human instead of storing a blank draft that looks like a finished reply.
    """
