"""Behaviour tests for the aggregator (M5 Phase 9).

M4's ``test_detectors.py`` asserts the *shape* of the contract and, for
aggregation, that the prose states the dedup rule. This module asserts the rule
itself, on the three properties that change what a persisted artifact says:

- identity is ``(category, value_fingerprint)`` — one entity, one finding;
- the survivor is the most confident sighting;
- ties keep the earliest sighting, which is what makes the winner depend only on
  detector chain order.

It also pins the scope limit the plan states twice and this milestone leans on
hard: **aggregation is per-leaf**. Merging two leaves that hold the same value
would let a remediation fix one path while the second keeps leaking
(ORDER §13.6), so the aggregator here has no notion of a leaf and the tests
assert that repeating a call is *not* a way to merge across paths.
"""

from __future__ import annotations

from app.pii import (
    DefaultPIIAggregator,
    InvalidPIIInputError,
    PIICategory,
    PIIFinding,
    PIISource,
)


def _finding(
    category: PIICategory = PIICategory.PERSON_NAME,
    value: str = "Смирнова Ольга Ивановна",
    fingerprint: str = "hmac-sha256:aaa",
    confidence: float = 0.8,
    detector: str = "pattern.person_name.three_token",
) -> PIIFinding:
    return PIIFinding(
        category=category,
        value=value,
        masked_value="С******* О**** И*******",
        value_fingerprint=fingerprint,
        confidence=confidence,
        source=PIISource.PATTERN,
        detector=detector,
        detector_version="1.1.0",
    )


# --- identity --------------------------------------------------------------


def test_the_same_entity_twice_is_one_finding():
    found = [_finding(), _finding(detector="structured.patient.full_name")]
    assert len(DefaultPIIAggregator().aggregate(found)) == 1


def test_a_different_category_for_the_same_value_is_not_a_duplicate():
    """Category is in the key on purpose.

    The same eleven digits read as a medical record number in one field and a
    national id in another are two *claims* about the document. Collapsing them
    would let the second one vanish because the first happened to be
    higher-confidence — and Phase 14 would then redact one label and leave the
    other in the artifact.
    """
    found = [
        _finding(category=PIICategory.MEDICAL_RECORD_NUMBER, fingerprint="hmac-sha256:aaa"),
        _finding(category=PIICategory.NATIONAL_ID, fingerprint="hmac-sha256:aaa"),
    ]
    assert len(DefaultPIIAggregator().aggregate(found)) == 2


def test_the_same_category_with_a_different_fingerprint_stays_separate():
    found = [_finding(fingerprint="hmac-sha256:aaa"), _finding(fingerprint="hmac-sha256:bbb")]
    assert len(DefaultPIIAggregator().aggregate(found)) == 2


# --- the survivor ----------------------------------------------------------


def test_the_most_confident_sighting_survives():
    low = _finding(confidence=0.6, detector="pattern.ticket_number.long_digits")
    high = _finding(confidence=0.95, detector="structured.patient.snils")
    kept = DefaultPIIAggregator().aggregate([low, high])
    assert [finding.detector for finding in kept] == ["structured.patient.snils"]


def test_confidence_beats_input_order():
    """Order must not decide the winner, or the result depends on fan-out luck."""
    high, low = _finding(confidence=0.95), _finding(confidence=0.6)
    assert DefaultPIIAggregator().aggregate([low, high]) == DefaultPIIAggregator().aggregate(
        [high, low]
    )


def test_a_tie_keeps_the_earliest_sighting():
    first = _finding(confidence=0.8, detector="first")
    second = _finding(confidence=0.8, detector="second")
    kept = DefaultPIIAggregator().aggregate([first, second])
    assert [finding.detector for finding in kept] == ["first"]


def test_an_earlier_weak_sighting_does_not_beat_a_later_strong_one():
    """The earliest rule is the *tie-break*, not a veto."""
    early = _finding(confidence=0.6, detector="early")
    late = _finding(confidence=0.9, detector="late")
    assert [f.detector for f in DefaultPIIAggregator().aggregate([early, late])] == ["late"]


# --- the empty-fingerprint escape hatch ------------------------------------


def test_a_finding_without_a_fingerprint_is_never_merged():
    """A fingerprint-less sighting carries no evidence it is the same entity.

    Merging on position instead would silently drop a real finding, so the
    over-report is deliberate: a detector that cannot fingerprint (Phase 1
    anticipated it) may duplicate, but it may never lose data.
    """
    anonymous = [
        _finding(fingerprint="", detector="guard.a"),
        _finding(fingerprint="", detector="guard.b"),
    ]
    assert len(DefaultPIIAggregator().aggregate(anonymous)) == 2


def test_an_anonymous_finding_does_not_absorb_a_fingerprinted_one():
    mixed = [
        _finding(fingerprint="", detector="guard.a"),
        _finding(fingerprint="hmac-sha256:aaa", detector="pattern.x"),
    ]
    assert len(DefaultPIIAggregator().aggregate(mixed)) == 2


# --- order, purity, degenerate input ---------------------------------------


def test_output_order_follows_first_appearance():
    found = [
        _finding(category=PIICategory.PERSON_NAME, fingerprint="hmac-sha256:bbb"),
        _finding(category=PIICategory.EMAIL, fingerprint="hmac-sha256:ccc"),
        _finding(category=PIICategory.PERSON_NAME, fingerprint="hmac-sha256:bbb"),
        _finding(category=PIICategory.PERSON_NAME, fingerprint="hmac-sha256:aaa"),
    ]
    kept = DefaultPIIAggregator().aggregate(found)
    assert [(f.category.value, f.value_fingerprint) for f in kept] == [
        ("person_name", "hmac-sha256:bbb"),
        ("email", "hmac-sha256:ccc"),
        ("person_name", "hmac-sha256:aaa"),
    ]


def test_the_input_list_is_not_mutated():
    found = [_finding(), _finding(detector="second")]
    before = list(found)
    DefaultPIIAggregator().aggregate(found)
    assert found == before


def test_empty_and_single_inputs_pass_through():
    assert DefaultPIIAggregator().aggregate([]) == []
    single = [_finding()]
    assert DefaultPIIAggregator().aggregate(single) == single


# --- per-leaf scope (ORDER §13.6) ------------------------------------------


def test_two_leaves_holding_the_same_value_stay_two_findings():
    """The §13.6 invariant, and the reason the leaf boundary is the caller's.

    Two payload paths holding the same patient's name are two separate findings.
    Merging them would let a remediation fix one path while the second keeps
    leaking — so the test asserts that the *only* thing keeping them apart is the
    caller calling ``aggregate`` once per leaf, and that aggregating the
    concatenation is precisely the mistake §13.6 forbids.
    """
    leaf_a = [_finding(detector="fields.note")]
    leaf_b = [_finding(detector="fields.summary")]

    per_leaf: list[PIIFinding] = []
    for leaf in (leaf_a, leaf_b):
        per_leaf.extend(DefaultPIIAggregator().aggregate(leaf))

    assert [f.detector for f in per_leaf] == ["fields.note", "fields.summary"]
    assert len(per_leaf) == 2

    # The forbidden shape, asserted so the failure mode is named rather than
    # merely avoided: one call over both leaves collapses them to one finding.
    assert len(DefaultPIIAggregator().aggregate(per_leaf)) == 1


def test_aggregation_is_idempotent():
    """A second pass has nothing left to collapse, so a repeat call is a no-op."""
    per_leaf = [
        _finding(fingerprint="hmac-sha256:aaa", detector="leaf.a"),
        _finding(fingerprint="hmac-sha256:bbb", value="Петров Иван Сергеевич", detector="leaf.b"),
    ]
    once = DefaultPIIAggregator().aggregate(per_leaf)
    assert len(once) == 2
    assert DefaultPIIAggregator().aggregate(once) == once


def test_an_unfingerprintable_finding_survives_a_failing_chain():
    """A detector that cannot fingerprint must not take the document down."""
    found = [_finding(fingerprint="", detector="broken.detector")]
    assert DefaultPIIAggregator().aggregate(found) == found


def test_aggregator_rejects_nothing_and_raises_nothing_business():
    """Sanity: the aggregator's only failure mode is the caller's, not its own.

    Exists because ``InvalidPIIInputError`` is imported by the Phase 9 suite and
    nothing here should raise it — an aggregator that validated its input would
    have to decide what a *valid* finding is, and that judgement belongs to the
    detector.
    """
    assert DefaultPIIAggregator() is not None
    try:
        DefaultPIIAggregator().aggregate([_finding(fingerprint="")])
    except InvalidPIIInputError:  # pragma: no cover - documented as unreachable
        raise AssertionError("aggregation must not validate findings") from None
