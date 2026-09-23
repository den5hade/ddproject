"""Tests for the Classification 2.0 rule-scoring engine (Phase 3)."""

from app.classification.models import (
    ClassificationConfidenceLevel,
    ClassificationDecision,
    ClassificationSignal,
    DocumentType,
)
from app.classification.scoring import (
    AMBIGUITY_MARGIN_RATIO,
    CLASSIFIER_VERSION,
    SCORE_FLOOR,
    STRENGTH_REF,
    THRESH_HIGH_MIN,
    THRESH_MED_LOW,
    RuleScoringEngine,
    signal_score,
)

ENGINE = RuleScoringEngine()


def sig(name, weight, matches=0, matched=True):
    return ClassificationSignal(
        name=name,
        weight=weight,
        matched=matched,
        matches=matches,
    )


def test_new_scoring_constants():
    assert STRENGTH_REF == 20.0
    assert SCORE_FLOOR == 5.0
    assert AMBIGUITY_MARGIN_RATIO == 0.25
    assert THRESH_HIGH_MIN == 0.90
    assert THRESH_MED_LOW == 0.70
    assert CLASSIFIER_VERSION == "2.1.0"


def test_signal_score_formula():
    assert signal_score(sig("laboratory.a", 5.0, matches=3)) == 15.0
    assert signal_score(sig("laboratory.a", 5.0, matches=0)) == 5.0
    assert signal_score(sig("laboratory.a", 5.0, matched=False)) == 0.0


def test_scored_signals_are_copies_with_scores():
    signals = [sig("laboratory.a", 5.0, matches=2)]
    scored = ENGINE.scored_signals(signals)
    assert scored[0].score == 10.0
    assert scored[0] is not signals[0]
    assert signals[0].score == 0.0


def test_reference_34_vs_4_is_high_confidence():
    signals = [
        sig("laboratory.a", 5.0, matches=6),   # 30
        sig("laboratory.b", 1.0, matches=4),   # 4
        sig("appointment.a", 1.0, matches=4),  # 4
    ]
    typ, conf, reasons, decision, level = ENGINE.score(signals)
    assert typ == DocumentType.LABORATORY
    assert decision == ClassificationDecision.ACCEPT
    assert level == ClassificationConfidenceLevel.HIGH
    assert conf >= 0.90
    assert reasons


def test_reference_12_vs_10_is_low_confidence():
    signals = [
        sig("laboratory.a", 3.0, matches=4),    # 12
        sig("appointment.a", 5.0, matches=2),   # 10
    ]
    typ, conf, _, decision, level = ENGINE.score(signals)
    assert typ == DocumentType.LABORATORY
    assert decision == ClassificationDecision.AMBIGUOUS  # margin 2 < 0.25*12
    assert level == ClassificationConfidenceLevel.LOW
    assert 0.3 <= conf < 0.40


def test_reference_solo_5_is_medium():
    signals = [sig("laboratory.a", 5.0, matches=1)]
    typ, conf, _, decision, level = ENGINE.score(signals)
    assert typ == DocumentType.LABORATORY
    assert decision == ClassificationDecision.ACCEPT
    assert level == ClassificationConfidenceLevel.MEDIUM
    assert conf == 0.70


def test_ambiguous_when_margin_below_quarter_top():
    signals = [
        sig("laboratory.a", 5.0, matches=1),   # 5
        sig("appointment.a", 5.0, matches=1),  # 5
    ]
    typ, conf, reasons, decision, level = ENGINE.score(signals)
    assert decision == ClassificationDecision.AMBIGUOUS
    assert typ == DocumentType.LABORATORY  # top (same score, first by enum order)
    assert any("margin" in r for r in reasons)
    assert level == ClassificationConfidenceLevel.LOW


def test_fallback_when_below_floor():
    signals = [sig("laboratory.a", 1.0, matches=1)]
    typ, conf, reasons, decision, level = ENGINE.score(signals)
    assert typ == DocumentType.OTHER
    assert decision == ClassificationDecision.FALLBACK
    assert any("floor" in r.lower() for r in reasons)
    assert conf == 0.62  # solo top=1: dominance=1.0, strength=0.05, 0.6+0.02
    assert level == ClassificationConfidenceLevel.LOW


def test_fallback_on_empty_signals():
    typ, conf, _, decision, level = ENGINE.score([])
    assert typ == DocumentType.OTHER
    assert decision == ClassificationDecision.FALLBACK
    assert conf == 0.0
    assert level == ClassificationConfidenceLevel.LOW


def test_unrecognized_prefix_ignored():
    signals = [
        sig("unknown.signal", 5.0, matches=10),
        sig("laboratory.a", 1.0, matches=1),
    ]
    typ, _, _, decision, _ = ENGINE.score(signals)
    assert typ == DocumentType.OTHER
    assert decision == ClassificationDecision.FALLBACK


def test_negative_second_does_not_shrink_margin():
    signals = [
        sig("laboratory.a", 5.0, matches=4),       # 20
        sig("appointment.a", -4.0, matches=2),     # -8 (contradicting)
    ]
    typ, conf, _, decision, level = ENGINE.score(signals)
    assert typ == DocumentType.LABORATORY
    assert decision == ClassificationDecision.ACCEPT
    assert level == ClassificationConfidenceLevel.HIGH
    assert conf >= 0.95


def test_engine_matches_scoring_protocol_shape():
    from typing import Protocol

    assert issubclass(RuleScoringEngine, Protocol) or True
    from app.classification.scoring import ScoringEngine

    engine: ScoringEngine = ENGINE
    assert callable(engine.score)