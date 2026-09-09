"""Offline stub classifier (``TRIAGE_FAKE_LLM=1``).

Purpose: run the API, the UI and the integration tests end to end without an API
key and without spending money. Keyword matching, not intelligence - this exists so
that developing the Streamlit queue view does not cost anything per page refresh.

It is **not** a baseline to compare against in the evaluation. Measuring the real
classifier against a keyword matcher would flatter it; ``eval/run_eval.py`` scores
against hand-labelled data instead.
"""

import re
import unicodedata
from decimal import Decimal

from ..domain.enums import Intent
from ..domain.models import Classification, UsageRecord

# Keywords are written without diacritics and matched against de-accented text.
# Polish customers write both "zwrócić" and "zwrocic"; a dev stub that only
# understood the first would be useless for exactly the messy input this system
# exists to handle.
_RULES: list[tuple[Intent, tuple[str, ...]]] = [
    (Intent.QUALITY_COMPLAINT, ("wadliw", "uszkodz", "zepsu", "reklamac", "peknie", "nie dziala")),
    (Intent.SHIPPING_STATUS, ("gdzie jest", "kiedy dotrze", "przesylk", "kurier", "sledzen")),
    (Intent.REFUND_STATUS, ("pieniadz", "przelew", "zwrot srodk", "kiedy zwrot")),
    (Intent.RETURN_NO_REASON, ("zwroc", "zwrot", "oddac", "odstap", "za mal", "za duz")),
]


def _fold(text: str) -> str:
    """Lowercase and strip diacritics: 'Zwrócić' -> 'zwrocic'."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    # 'ł' has no combining form, so NFKD leaves it alone - map it explicitly.
    return "".join(c for c in decomposed if not unicodedata.combining(c)).replace("ł", "l")


class FakeClassifier:
    """Deterministic keyword classifier with the same interface as the real one."""

    def __init__(self, *, model: str = "fake", usd_to_pln: Decimal = Decimal("0")) -> None:
        self._model = model
        self._usd_to_pln = usd_to_pln

    def classify(self, ticket_text: str) -> tuple[Classification, UsageRecord]:
        folded = _fold(ticket_text)

        intent, confidence = Intent.OTHER, 0.3
        for candidate, keywords in _RULES:
            if any(kw in folded for kw in keywords):
                intent, confidence = candidate, 0.8
                break

        classification = Classification(
            intent=intent,
            order_ref=_extract_order_ref(ticket_text),
            confidence=confidence,
            reasoning="Klasyfikacja zastępcza (tryb offline) - dopasowanie słów kluczowych.",
        )
        # Zero tokens, zero cost: nothing was actually called.
        return classification, UsageRecord(model=self._model)


def _extract_order_ref(text: str) -> str | None:
    """Pull the first 4+ digit run out of the text."""
    match = re.search(r"\b(\d{4,})\b", text)
    return match.group(1) if match else None


class FakeResponder:
    """Offline stand-in for the reply generator.

    Templated, not written - it exists so the operator queue in Streamlit has
    something to render without an API key. The template deliberately reads as a
    template so nobody mistakes offline output for a real draft.
    """

    def __init__(self, *, model: str = "fake") -> None:
        self._model = model

    def generate(self, *, ticket_text, classification, order, policy):  # noqa: ANN001, ANN201
        ref = f" (zamówienie {order.order_ref})" if order else ""
        body = (
            f"Dzień dobry,\n\n"
            f"dziękujemy za wiadomość{ref}. {policy.reason_pl}\n\n"
            f"[ODPOWIEDŹ ZASTĘPCZA - tryb offline, model nie został wywołany]\n\n"
            f"Pozdrawiamy,\nObsługa Klienta"
        )
        return body, UsageRecord(model=self._model)
