"""Scoring/decision contract and versioning (Classification 2.0).

Contract constants plus the concrete ``RuleScoringEngine`` (M2 Phase 3) that
converts detection signals into the scoring tuple returned by the
``ScoringEngine`` protocol.

Scoring (§4 of IMPL_PLAN):
``score_type = Σ scores of signals with prefix "<document_type>."``
``top = max score; second = 2nd; margin = top − second (second=0 if solo)``
``dominance = margin / max(top, 1.0)``
``strength  = min(1.0, top / STRENGTH_REF)``
``confidence = clamp01(0.6*dominance + 0.4*strength)``
``level = HIGH if ≥0.90 else MEDIUM if ≥0.70 else LOW``
decision: FALLBACK if ``top < SCORE_FLOOR`` → ``other``; AMBIGUOUS if
``margin < AMBIGUITY_MARGIN_RATIO * top`` (decision preserved, extraction via
generic); else ACCEPT.

Calibration of weights/thresholds is deferred to M3 evaluation — the engine
computes the documented rules without re-tuning them.
"""

from typing import Protocol

from app.classification.models import (
    ClassificationConfidenceLevel,
    ClassificationDecision,
    ClassificationSignal,
    DocumentType,
)

CLASSIFIER_VERSION = "2.0.0"
"""Classification contract version (SemVer). Baseline for M1."""

# Contract constants.
WEIGHT_STRONG = 5.0
WEIGHT_MEDIUM = 3.0
WEIGHT_WEAK = 1.0
WEIGHT_CONTRADICTING = -4.0

# Confidence thresholds: 0.90–1.00 -> HIGH, 0.70–0.89 -> MEDIUM, < 0.70 -> LOW.
THRESH_HIGH_MIN = 0.90
THRESH_MED_LOW = 0.70

# Strength flattening reference: top / STRENGTH_REF caps `strength` at 1.0.
STRENGTH_REF = 20.0
# Absolute floor below which no type is accepted (decision FALLBACK -> other).
SCORE_FLOOR = 5.0
# Relative margin (of the top score) below which the decision is AMBIGUOUS.
AMBIGUITY_MARGIN_RATIO = 0.25


def signal_score(signal: ClassificationSignal) -> float:
    """Per-signal score: ``weight × matches`` (``matches > 0``) else ``weight``."""
    if signal.matches > 0:
        return signal.weight * signal.matches
    return signal.weight if signal.matched else 0.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


class ScoringEngine(Protocol):
    """Protocol for engines that convert signals into a classification."""

    def score(
        self,
        signals: list[ClassificationSignal],
    ) -> tuple[
        DocumentType,
        float,
        list[str],
        ClassificationDecision,
        ClassificationConfidenceLevel,
    ]:
        """Score ``signals`` into a decision tuple.

        Returns ``(document_type, confidence, reasons, decision,
        confidence_level)``.
        """
        ...


class RuleScoringEngine(ScoringEngine):
    """Deterministic rule-scoring engine (M2 Phase 3).

    Aggregates per-document-type totals from the ``<document_type>.`` prefix
    of each signal, applies the margin/strength confidence formula and the
    FALLBACK/AMBIGUOUS/ACCEPT decision rules documented above.
    """

    def scored_signals(self, signals: list[ClassificationSignal]) -> list[ClassificationSignal]:
        """Return ``signals`` as copies with ``score`` filled in."""
        return [
            signal.model_copy(update={"score": signal_score(signal)})
            for signal in signals
        ]

    def score(
        self,
        signals: list[ClassificationSignal],
    ) -> tuple[
        DocumentType,
        float,
        list[str],
        ClassificationDecision,
        ClassificationConfidenceLevel,
    ]:
        totals = self._type_totals(signals)
        top_type, top, second, margin = self._ranked(totals)
        confidence = self._confidence(top, margin)
        level = self._level(confidence)
        decision, document_type, reasons = self._decide(top, margin, top_type, level)
        return document_type, confidence, reasons, decision, level

    @staticmethod
    def _type_totals(signals: list[ClassificationSignal]) -> dict[DocumentType, float]:
        """Sum per-signal scores by the ``<document_type>.`` name prefix."""
        totals = {document_type: 0.0 for document_type in DocumentType}
        valid = {document_type.value for document_type in DocumentType}
        for signal in signals:
            prefix = signal.name.split(".", 1)[0]
            if prefix in valid:
                totals[DocumentType(prefix)] += signal_score(signal)
        return totals

    @staticmethod
    def _ranked(totals: dict[DocumentType, float]) -> tuple[DocumentType, float, float, float]:
        """Return ``(top_type, top, second, margin)`` (second=0.0 when solo)."""
        ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
        top_type, top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        return top_type, top, second, top - second

    @staticmethod
    def _confidence(top: float, margin: float) -> float:
        if top <= 0.0:
            return 0.0
        dominance = margin / max(top, 1.0)
        strength = min(1.0, top / STRENGTH_REF)
        return _clamp01(0.6 * dominance + 0.4 * strength)

    @staticmethod
    def _level(confidence: float) -> ClassificationConfidenceLevel:
        if confidence >= THRESH_HIGH_MIN:
            return ClassificationConfidenceLevel.HIGH
        if confidence >= THRESH_MED_LOW:
            return ClassificationConfidenceLevel.MEDIUM
        return ClassificationConfidenceLevel.LOW

    @staticmethod
    def _decide(
        top: float,
        margin: float,
        top_type: DocumentType,
        level: ClassificationConfidenceLevel,
    ) -> tuple[ClassificationDecision, DocumentType, list[str]]:
        if top < SCORE_FLOOR:
            return (
                ClassificationDecision.FALLBACK,
                DocumentType.OTHER,
                [f"top score {top:.1f} below SCORE_FLOOR {SCORE_FLOOR:.1f}"],
            )
        if margin < AMBIGUITY_MARGIN_RATIO * top:
            return (
                ClassificationDecision.AMBIGUOUS,
                top_type,
                [
                    f"top {top_type.value} {top:.1f}, margin {margin:.1f} "
                    f"below {AMBIGUITY_MARGIN_RATIO:.0%} of top",
                ],
            )
        return (
            ClassificationDecision.ACCEPT,
            top_type,
            [f"accepted {top_type.value} (top {top:.1f}, margin {margin:.1f}, {level.value})"],
        )


__all__ = [
    "AMBIGUITY_MARGIN_RATIO",
    "CLASSIFIER_VERSION",
    "RuleScoringEngine",
    "SCORE_FLOOR",
    "STRENGTH_REF",
    "ScoringEngine",
    "THRESH_HIGH_MIN",
    "THRESH_MED_LOW",
    "WEIGHT_CONTRADICTING",
    "WEIGHT_MEDIUM",
    "WEIGHT_STRONG",
    "WEIGHT_WEAK",
    "signal_score",
]