"""Tests for the auto-vs-human decision.

This module decides whether a customer gets an automatic answer or a person, so
every escalation trigger gets its own test, plus the boundary of the threshold and
the case where several reasons fire at once. No API key, no network.
"""

import pytest

from ticket_triage.domain.enums import (
    Decision,
    EscalationReason,
    Intent,
    PolicyOutcome,
)
from ticket_triage.domain.models import Classification, PolicyResult
from ticket_triage.triage.decision import DecisionEngine

THRESHOLD = 0.75


@pytest.fixture
def engine() -> DecisionEngine:
    return DecisionEngine(THRESHOLD)


def make_classification(
    *, intent: Intent = Intent.RETURN_NO_REASON, confidence: float = 0.95
) -> Classification:
    return Classification(intent=intent, order_ref="10432", confidence=confidence, reasoning="test")


def make_policy(
    *,
    outcome: PolicyOutcome = PolicyOutcome.ALLOWED,
    high_value: bool = False,
    keywords: list[str] | None = None,
) -> PolicyResult:
    return PolicyResult(
        outcome=outcome,
        reason_pl="powód testowy",
        rule_id="test.rule",
        days_since_purchase=3,
        high_value_order=high_value,
        legal_keywords_found=keywords or [],
    )


class TestHappyPath:
    def test_clean_ticket_is_answered_automatically(self, engine, order_factory):
        result = engine.decide(
            classification=make_classification(),
            order=order_factory(),
            policy=make_policy(),
        )
        assert result.decision is Decision.AUTO_REPLY
        assert result.reasons == []
        assert result.escalated is False

    def test_a_rejection_can_still_be_automatic(self, engine, order_factory):
        """A confident, unambiguous 'no' does not need a human to deliver it."""
        result = engine.decide(
            classification=make_classification(),
            order=order_factory(),
            policy=make_policy(outcome=PolicyOutcome.REJECTED),
        )
        assert result.decision is Decision.AUTO_REPLY

    def test_threshold_used_is_recorded(self, engine, order_factory):
        """Old rows must stay interpretable after the threshold is retuned."""
        result = engine.decide(
            classification=make_classification(),
            order=order_factory(),
            policy=make_policy(),
        )
        assert result.threshold_used == THRESHOLD


class TestLowConfidence:
    @pytest.mark.parametrize("confidence", [0.0, 0.5, 0.74])
    def test_below_threshold_escalates(self, engine, order_factory, confidence):
        result = engine.decide(
            classification=make_classification(confidence=confidence),
            order=order_factory(),
            policy=make_policy(),
        )
        assert result.decision is Decision.ESCALATE
        assert EscalationReason.LOW_CONFIDENCE in result.reasons

    def test_exactly_at_threshold_is_accepted(self, engine, order_factory):
        """`confidence < threshold` escalates, so the threshold itself passes."""
        result = engine.decide(
            classification=make_classification(confidence=THRESHOLD),
            order=order_factory(),
            policy=make_policy(),
        )
        assert result.decision is Decision.AUTO_REPLY

    def test_just_below_threshold_escalates(self, engine, order_factory):
        result = engine.decide(
            classification=make_classification(confidence=THRESHOLD - 0.01),
            order=order_factory(),
            policy=make_policy(),
        )
        assert EscalationReason.LOW_CONFIDENCE in result.reasons


class TestUnknownIntent:
    def test_other_intent_always_escalates(self, engine, order_factory):
        """Even at maximum confidence - we do not auto-answer what we never modelled."""
        result = engine.decide(
            classification=make_classification(intent=Intent.OTHER, confidence=1.0),
            order=order_factory(),
            policy=make_policy(outcome=PolicyOutcome.NOT_APPLICABLE),
        )
        assert result.decision is Decision.ESCALATE
        assert EscalationReason.UNKNOWN_INTENT in result.reasons

    def test_other_intent_does_not_also_report_missing_order(self, engine):
        """Checks 2 and 3 must not both fire - duplicate reasons are noise."""
        result = engine.decide(
            classification=make_classification(intent=Intent.OTHER),
            order=None,
            policy=make_policy(outcome=PolicyOutcome.NOT_APPLICABLE),
        )
        assert result.reasons == [EscalationReason.UNKNOWN_INTENT]


class TestMissingOrder:
    def test_missing_order_escalates(self, engine):
        result = engine.decide(
            classification=make_classification(),
            order=None,
            policy=make_policy(outcome=PolicyOutcome.AMBIGUOUS),
        )
        assert result.decision is Decision.ESCALATE
        assert EscalationReason.ORDER_NOT_FOUND in result.reasons

    def test_missing_order_does_not_also_report_ambiguous_policy(self, engine):
        """The policy is ambiguous *because* the order is missing - report it once."""
        result = engine.decide(
            classification=make_classification(),
            order=None,
            policy=make_policy(outcome=PolicyOutcome.AMBIGUOUS),
        )
        assert EscalationReason.AMBIGUOUS_POLICY not in result.reasons
        assert result.reasons == [EscalationReason.ORDER_NOT_FOUND]

    def test_shipping_question_without_an_order_escalates(self, engine):
        """No policy question, but we still cannot say where the parcel is."""
        result = engine.decide(
            classification=make_classification(intent=Intent.SHIPPING_STATUS),
            order=None,
            policy=make_policy(outcome=PolicyOutcome.NOT_APPLICABLE),
        )
        assert EscalationReason.ORDER_NOT_FOUND in result.reasons


class TestAmbiguousPolicy:
    def test_ambiguous_with_an_order_present_escalates(self, engine, order_factory):
        """e.g. a purchase date in the future - corrupt data, not a missing lookup."""
        result = engine.decide(
            classification=make_classification(),
            order=order_factory(),
            policy=make_policy(outcome=PolicyOutcome.AMBIGUOUS),
        )
        assert result.decision is Decision.ESCALATE
        assert result.reasons == [EscalationReason.AMBIGUOUS_POLICY]


class TestHardRules:
    def test_high_value_order_escalates_even_when_allowed(self, engine, order_factory):
        result = engine.decide(
            classification=make_classification(),
            order=order_factory(),
            policy=make_policy(outcome=PolicyOutcome.ALLOWED, high_value=True),
        )
        assert result.decision is Decision.ESCALATE
        assert result.reasons == [EscalationReason.HIGH_VALUE_ORDER]

    def test_legal_keyword_escalates_even_when_allowed(self, engine, order_factory):
        """The customer gets their money back either way - but a person sends that."""
        result = engine.decide(
            classification=make_classification(),
            order=order_factory(),
            policy=make_policy(outcome=PolicyOutcome.ALLOWED, keywords=["uokik"]),
        )
        assert result.decision is Decision.ESCALATE
        assert result.reasons == [EscalationReason.LEGAL_KEYWORD]


class TestMultipleReasons:
    def test_every_applicable_reason_is_collected(self, engine):
        """Reasons are a list, not a single value - the operator sees all of them."""
        result = engine.decide(
            classification=make_classification(confidence=0.4),
            order=None,
            policy=make_policy(outcome=PolicyOutcome.AMBIGUOUS, high_value=False, keywords=["sąd"]),
        )
        assert result.reasons == [
            EscalationReason.LOW_CONFIDENCE,
            EscalationReason.ORDER_NOT_FOUND,
            EscalationReason.LEGAL_KEYWORD,
        ]

    def test_reason_order_is_stable(self, engine, order_factory):
        """Fixed order keeps the operator panel and stored rows predictable."""
        result = engine.decide(
            classification=make_classification(confidence=0.1),
            order=order_factory(),
            policy=make_policy(high_value=True, keywords=["prawnik"]),
        )
        assert result.reasons == [
            EscalationReason.LOW_CONFIDENCE,
            EscalationReason.HIGH_VALUE_ORDER,
            EscalationReason.LEGAL_KEYWORD,
        ]


class TestForceEscalation:
    def test_downgrades_an_auto_reply(self, engine, order_factory):
        base = engine.decide(
            classification=make_classification(),
            order=order_factory(),
            policy=make_policy(),
        )
        assert base.decision is Decision.AUTO_REPLY

        forced = DecisionEngine.force_escalation(base, EscalationReason.GENERATION_FAILED)
        assert forced.decision is Decision.ESCALATE
        assert forced.reasons == [EscalationReason.GENERATION_FAILED]
        assert forced.threshold_used == base.threshold_used

    def test_keeps_existing_reasons(self, engine):
        base = engine.decide(
            classification=make_classification(confidence=0.2),
            order=None,
            policy=make_policy(outcome=PolicyOutcome.AMBIGUOUS),
        )
        forced = DecisionEngine.force_escalation(base, EscalationReason.GENERATION_FAILED)
        assert EscalationReason.LOW_CONFIDENCE in forced.reasons
        assert EscalationReason.GENERATION_FAILED in forced.reasons

    def test_is_idempotent(self, engine, order_factory):
        base = engine.decide(
            classification=make_classification(),
            order=order_factory(),
            policy=make_policy(),
        )
        once = DecisionEngine.force_escalation(base, EscalationReason.GENERATION_FAILED)
        twice = DecisionEngine.force_escalation(once, EscalationReason.GENERATION_FAILED)
        assert twice.reasons == once.reasons


class TestConstruction:
    @pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0])
    def test_threshold_outside_zero_to_one_is_rejected(self, bad):
        with pytest.raises(ValueError, match="confidence_threshold"):
            DecisionEngine(bad)

    @pytest.mark.parametrize("ok", [0.0, 0.5, 1.0])
    def test_valid_thresholds_are_accepted(self, ok):
        assert DecisionEngine(ok).threshold == ok

    def test_threshold_zero_still_escalates_on_other_rules(self, order_factory):
        """Setting the threshold to 0 disables check 1 only, not the other five."""
        result = DecisionEngine(0.0).decide(
            classification=make_classification(confidence=0.0),
            order=order_factory(),
            policy=make_policy(keywords=["uokik"]),
        )
        assert result.reasons == [EscalationReason.LEGAL_KEYWORD]
