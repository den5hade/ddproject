"""Scoring/decision contract and versioning (Classification 2.0).

Contract constants and ``ScoringEngine`` protocol only — no scoring algorithm
is implemented in M1. Weights, thresholds and the margin rule below are
informational contract constants; calibration is deferred to evaluation (M3),
so nothing here is computed at runtime.
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

# Contract constants — not computed in M1.
WEIGHT_STRONG = 5.0
WEIGHT_MEDIUM = 3.0
WEIGHT_WEAK = 1.0
WEIGHT_CONTRADICTING = -4.0

# Confidence thresholds (documented, calibration deferred to M3):
# 0.90–1.00 -> HIGH, 0.70–0.89 -> MEDIUM, < 0.70 -> LOW.
THRESH_HIGH_MIN = 0.90
THRESH_MED_LOW = 0.70

# Margin rule (documented): the decision is AMBIGUOUS when
# ``top_score - second_score`` falls below the margin threshold. The numeric
# margin value is defined during evaluation; not enforced in M1.


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
        confidence_level)``. Contract only — no implementation in M1.
        """
        ...


__all__ = [
    "CLASSIFIER_VERSION",
    "ScoringEngine",
    "THRESH_HIGH_MIN",
    "THRESH_MED_LOW",
    "WEIGHT_CONTRADICTING",
    "WEIGHT_MEDIUM",
    "WEIGHT_STRONG",
    "WEIGHT_WEAK",
]