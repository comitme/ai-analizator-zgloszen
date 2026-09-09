"""Domain vocabulary.

Enum *values* are stable, lowercase, English identifiers - they are written to the
database and to the LLM's JSON schema, so they must not change casually. Polish
labels for the operator UI live in the ``*_LABELS_PL`` mappings at the bottom.
"""

from enum import StrEnum


class Intent(StrEnum):
    """What the customer is actually asking for."""

    QUALITY_COMPLAINT = "quality_complaint"
    """Reklamacja jakości - product is faulty, damaged or not as described."""

    RETURN_NO_REASON = "return_no_reason"
    """Zwrot bez podania przyczyny - statutory 14-day withdrawal from a distance contract."""

    SHIPPING_STATUS = "shipping_status"
    """Pytanie o status wysyłki - where is my parcel."""

    REFUND_STATUS = "refund_status"
    """Pytanie o zwrot pieniędzy - money owed back, or when it will arrive."""

    OTHER = "other"
    """Anything else. Always escalated - we do not auto-answer what we did not model."""


class PolicyOutcome(StrEnum):
    """Result of evaluating the shop's return policy against the facts."""

    ALLOWED = "allowed"
    """The request is covered by the policy."""

    REJECTED = "rejected"
    """The request is not covered, and we know why."""

    AMBIGUOUS = "ambiguous"
    """Not enough facts to decide (e.g. order not found). Always escalates."""

    NOT_APPLICABLE = "not_applicable"
    """No return policy question here (e.g. the customer just asked where the parcel is)."""


class Decision(StrEnum):
    """What the system does with the ticket."""

    AUTO_REPLY = "auto_reply"
    ESCALATE = "escalate"


class EscalationReason(StrEnum):
    """Why a ticket went to a human. Multiple reasons can apply at once."""

    LOW_CONFIDENCE = "low_confidence"
    """Classifier confidence below the configured threshold."""

    UNKNOWN_INTENT = "unknown_intent"
    """Intent is OTHER - outside what the system was designed to answer."""

    ORDER_NOT_FOUND = "order_not_found"
    """No order reference extracted, or the reference does not match any order."""

    AMBIGUOUS_POLICY = "ambiguous_policy"
    """Policy engine could not reach a definite outcome."""

    HIGH_VALUE_ORDER = "high_value_order"
    """Order value above the configured escalation threshold."""

    LEGAL_KEYWORD = "legal_keyword"
    """Ticket mentions a legal-dispute signal (UOKiK, sąd, prawnik, ...)."""


class TicketStatus(StrEnum):
    """Lifecycle of a ticket in the operator queue."""

    NEW = "new"
    """Accepted, not yet triaged."""

    TRIAGED = "triaged"
    """Pipeline ran; a draft reply is waiting for a human to approve."""

    ESCALATED = "escalated"
    """Pipeline ran; a human must handle this one from scratch."""

    ANSWERED = "answered"
    """An operator sent a reply (approved, edited or written from scratch)."""

    FAILED = "failed"
    """Pipeline errored. Kept visible so nothing silently disappears."""


INTENT_LABELS_PL: dict[Intent, str] = {
    Intent.QUALITY_COMPLAINT: "Reklamacja jakości",
    Intent.RETURN_NO_REASON: "Zwrot bez podania przyczyny",
    Intent.SHIPPING_STATUS: "Pytanie o status wysyłki",
    Intent.REFUND_STATUS: "Pytanie o zwrot pieniędzy",
    Intent.OTHER: "Inne",
}

ESCALATION_LABELS_PL: dict[EscalationReason, str] = {
    EscalationReason.LOW_CONFIDENCE: "Niska pewność klasyfikacji",
    EscalationReason.UNKNOWN_INTENT: "Nierozpoznana intencja",
    EscalationReason.ORDER_NOT_FOUND: "Nie znaleziono zamówienia",
    EscalationReason.AMBIGUOUS_POLICY: "Niejednoznaczna ocena polityki",
    EscalationReason.HIGH_VALUE_ORDER: "Zamówienie o wysokiej wartości",
    EscalationReason.LEGAL_KEYWORD: "Sygnał sporu prawnego",
}
