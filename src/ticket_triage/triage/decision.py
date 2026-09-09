"""Auto-reply, or hand the ticket to a human.

Six independent checks, evaluated in a fixed order. **Any one of them escalates.**
The confidence threshold is only one of the six, and deliberately so: a language
model's self-reported confidence is poorly calibrated - it can be confident and
wrong at the same time. Treating that number as the sole gate would be trusting the
one signal least worth trusting.

Like the policy engine, nothing here calls a model. Given a classification, an order
and a policy verdict, the decision is a pure function of its inputs.
"""

from ..domain.enums import Decision, EscalationReason, Intent, PolicyOutcome
from ..domain.models import Classification, DecisionResult, Order, PolicyResult


class DecisionEngine:
    """Turns a policy verdict plus a classification into auto-vs-human."""

    def __init__(self, confidence_threshold: float) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError(
                f"confidence_threshold must be within [0.0, 1.0], got {confidence_threshold!r}"
            )
        self._threshold = confidence_threshold

    @property
    def threshold(self) -> float:
        """Exposed so ``eval/threshold_sweep.py`` can report the setting it measured."""
        return self._threshold

    def decide(
        self,
        *,
        classification: Classification,
        order: Order | None,
        policy: PolicyResult,
    ) -> DecisionResult:
        """Collect every reason to escalate. Empty list means the ticket can be answered."""
        reasons: list[EscalationReason] = []

        # 1. The model was not sure enough. Threshold comes from config/app.yaml and is
        #    tuned against the evaluation set, not guessed.
        if classification.confidence < self._threshold:
            reasons.append(EscalationReason.LOW_CONFIDENCE)

        # 2. Outside the five intents the system was designed for. We do not
        #    auto-answer what we never modelled.
        if classification.intent is Intent.OTHER:
            reasons.append(EscalationReason.UNKNOWN_INTENT)

        # 3. We needed order facts and do not have them - the customer gave no number,
        #    or the number matched nothing. OTHER is excluded because check 2 already
        #    covers it and a second reason would just be noise for the operator.
        if order is None and classification.intent is not Intent.OTHER:
            reasons.append(EscalationReason.ORDER_NOT_FOUND)

        # 4. The policy could not reach a definite verdict for some reason *other* than
        #    the missing order (e.g. a purchase date in the future - corrupt data).
        #    Scoped this way so checks 3 and 4 never report the same problem twice.
        if policy.outcome is PolicyOutcome.AMBIGUOUS and order is not None:
            reasons.append(EscalationReason.AMBIGUOUS_POLICY)

        # 5-6. Hard rules from return_policy.yaml. These fire regardless of how
        #      confident the model was or how clear the policy verdict is - an
        #      allowed return worth 3 500 zł still gets a human, and so does a
        #      ticket that mentions going to court.
        if policy.high_value_order:
            reasons.append(EscalationReason.HIGH_VALUE_ORDER)

        if policy.legal_keywords_found:
            reasons.append(EscalationReason.LEGAL_KEYWORD)

        return DecisionResult(
            decision=Decision.ESCALATE if reasons else Decision.AUTO_REPLY,
            reasons=reasons,
            threshold_used=self._threshold,
        )

    @staticmethod
    def force_escalation(
        base: DecisionResult, reason: EscalationReason
    ) -> DecisionResult:
        """Downgrade an existing decision to ESCALATE, adding one reason.

        Used when something operational fails after the decision was made - the reply
        could not be drafted, say. Kept here rather than mutating the result inline so
        that "a decision changed, and here is the reason" stays a single, greppable
        operation.
        """
        if reason in base.reasons:
            return base
        return DecisionResult(
            decision=Decision.ESCALATE,
            reasons=[*base.reasons, reason],
            threshold_used=base.threshold_used,
        )
