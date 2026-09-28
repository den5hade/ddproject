"""Behaviour tests for the policy engine (M5 Phase 9).

M4's ``test_policy_gate.py`` asserts the table *transcription* — that
``DEFAULT_POLICY``'s rows equal the locked §4.4 values, category by category.
This module asserts what the engine does with that table: the destination
overrides, the redact-unavailable escalation, the reduction to one decision, and
the empty-document case.

Every decision here is a *fail-safe* claim, so the tests are written to be
readable as claims about the pipeline: a ``BLOCK`` halts, a ``REVIEW`` halts for a
different reason, and an ``ALLOW`` is the only outcome that lets a document
through with nobody having looked at it.
"""

from __future__ import annotations

import pytest
from app.pii import (
    CATEGORY_RISK,
    DEFAULT_POLICY,
    RISK_ORDER,
    PIIAction,
    PIICategory,
    PIIDecision,
    PIIDestination,
    PIIFinding,
    PIIPolicyContext,
    PIIRiskLevel,
    PIIRule,
    PIIScanStage,
    PIISource,
)
from app.pii.policy import REDACT_ON_EXTERNAL, DefaultPolicyEngine

ORGANIZATION = "tenant-1"


def _finding(category: PIICategory, confidence: float = 0.9) -> PIIFinding:
    return PIIFinding(
        category=category,
        value="x",
        masked_value="X",
        value_fingerprint=f"hmac-sha256:{category.value}",
        confidence=confidence,
        source=PIISource.PATTERN,
        detector="test.finding",
        detector_version="1.1.0",
    )


def _context(
    destination: PIIDestination = PIIDestination.INTERNAL_LLM,
    *,
    redaction_available: bool = False,
    stage: PIIScanStage = PIIScanStage.DOCUMENT,
) -> PIIPolicyContext:
    return PIIPolicyContext(
        destination=destination,
        stage=stage,
        organization_id=ORGANIZATION,
        redaction_available=redaction_available,
    )


# --- one row per category (plan: "policy table row per category") ----------


def test_every_category_resolves_to_its_own_action_and_risk_at_the_internal_destination():
    """A row per category, exercised one category at a time.

    Parametrised over the taxonomy rather than a hand-written list so a new
    category cannot arrive without a row here — the completeness check in
    ``PIIPolicy`` would allow it, and only this test would notice.
    """
    engine = DefaultPolicyEngine()
    for category in PIICategory:
        result = engine.evaluate([_finding(category)], _context())
        assert result.actions == {category: DEFAULT_POLICY.action_for(category)}
        assert result.risk_level is CATEGORY_RISK[category], category


def test_only_a_secret_blocks_on_the_base_table():
    """PII presence alone never halts a document.

    A medical record is *expected* to carry a name, a date of birth and a
    medical record number; blocking on those would halt every document the
    platform exists to process.
    """
    engine = DefaultPolicyEngine()
    for category in PIICategory:
        if category is PIICategory.SECRET:
            continue
        assert engine.evaluate([_finding(category)], _context()).decision is PIIDecision.ALLOW
    assert engine.evaluate([_finding(PIICategory.SECRET)], _context()).decision is PIIDecision.BLOCK


# --- risk is the maximum, not the last --------------------------------------


def test_risk_is_the_maximum_across_categories():
    engine = DefaultPolicyEngine()
    result = engine.evaluate(
        [
            _finding(PIICategory.EMAIL),  # low
            _finding(PIICategory.PERSON_NAME),  # medium
            _finding(PIICategory.SNILS),  # high
        ],
        _context(),
    )
    assert result.risk_level is PIIRiskLevel.HIGH


def test_a_secret_outranks_every_identifier_in_risk():
    engine = DefaultPolicyEngine()
    result = engine.evaluate(
        [_finding(PIICategory.SNILS), _finding(PIICategory.SECRET)],
        _context(),
    )
    assert result.risk_level is PIIRiskLevel.CRITICAL
    assert result.decision is PIIDecision.BLOCK


def test_an_empty_scan_is_allow_at_low():
    engine = DefaultPolicyEngine()
    result = engine.evaluate([], _context())
    assert result.decision is PIIDecision.ALLOW
    assert result.risk_level is PIIRiskLevel.LOW
    assert result.actions == {}
    assert result.reasons


# --- destination overrides --------------------------------------------------


@pytest.mark.parametrize("destination", [PIIDestination.INTERNAL_LLM, PIIDestination.PERSISTENCE])
def test_trusted_destinations_use_the_base_table_unchanged(destination):
    engine = DefaultPolicyEngine()
    result = engine.evaluate([_finding(PIICategory.PERSON_NAME)], _context(destination))
    assert result.actions == {PIICategory.PERSON_NAME: PIIAction.ALLOW}
    assert result.decision is PIIDecision.ALLOW


def test_external_redacts_the_four_patient_groups():
    """All 18 of them, and none of the 5 excluded ones — counted, not listed.

    Asserting the *count* alongside membership is what catches a group silently
    gaining or losing a category: the exclusion is as much a security claim as
    the inclusion.
    """
    engine = DefaultPolicyEngine()
    assert len(REDACT_ON_EXTERNAL) == 18
    assert REDACT_ON_EXTERNAL.isdisjoint(
        {
            PIICategory.DOCTOR_NAME,
            PIICategory.DOCTOR_LICENSE,
            PIICategory.ORGANIZATION_NAME,
            PIICategory.ORGANIZATION_ID,
            PIICategory.SECRET,
        }
    )
    redacting = _context(PIIDestination.EXTERNAL_LLM, redaction_available=True)
    for category in REDACT_ON_EXTERNAL:
        result = engine.evaluate([_finding(category)], redacting)
        assert result.actions[category] is PIIAction.REDACT, category


def test_external_leaves_the_practitioner_group_alone():
    """A clinic's name is not patient PII, and a secret is not made safer by masking.

    §7 decision on the medical/practitioner split: redacting ``doctor_name`` or
    ``organization_name`` destroys what ``render_document`` needs, which is the
    mistake this taxonomy exists to prevent.
    """
    engine = DefaultPolicyEngine()
    for category in (
        PIICategory.DOCTOR_NAME,
        PIICategory.DOCTOR_LICENSE,
        PIICategory.ORGANIZATION_NAME,
        PIICategory.ORGANIZATION_ID,
    ):
        result = engine.evaluate([_finding(category)], _context(PIIDestination.EXTERNAL_LLM))
        assert result.actions[category] is PIIAction.ALLOW, category


def test_external_still_blocks_a_secret_rather_than_redacting_it():
    engine = DefaultPolicyEngine()
    result = engine.evaluate([_finding(PIICategory.SECRET)], _context(PIIDestination.EXTERNAL_LLM))
    assert result.actions[PIICategory.SECRET] is PIIAction.BLOCK
    assert result.decision is PIIDecision.BLOCK


def test_an_unknown_destination_forces_review():
    """Failing closed is the whole point of the enum.

    A destination nobody can reason about is not a destination that may receive
    a document — and the enum exists so that this state is expressible.
    """
    engine = DefaultPolicyEngine()
    result = engine.evaluate([_finding(PIICategory.EMAIL)], _context(PIIDestination.UNKNOWN))
    assert result.actions[PIICategory.EMAIL] is PIIAction.REVIEW
    assert result.decision is PIIDecision.REVIEW
    assert any("unknown" in reason for reason in result.reasons)


def test_an_unknown_destination_does_not_downgrade_a_block():
    engine = DefaultPolicyEngine()
    result = engine.evaluate([_finding(PIICategory.SECRET)], _context(PIIDestination.UNKNOWN))
    assert result.decision is PIIDecision.BLOCK


# --- the redact-unavailable escalation --------------------------------------


def test_redact_without_a_redactor_escalates_to_review():
    """The contradiction resolves upward, never downward.

    A document that *must* be redacted and cannot be is a document a human has
    to look at. Silently allowing it would send unredacted PII to an external
    provider while the artifact claimed the document was merely reviewed.
    """
    engine = DefaultPolicyEngine()
    result = engine.evaluate(
        [_finding(PIICategory.PERSON_NAME)],
        _context(PIIDestination.EXTERNAL_LLM, redaction_available=False),
    )
    assert result.actions[PIICategory.PERSON_NAME] is PIIAction.REVIEW
    assert result.decision is PIIDecision.REVIEW
    assert any("redact" in reason for reason in result.reasons)


def test_redact_with_a_redactor_is_the_only_allow_with_warning():
    """Once Phase 12 lands, this combination is the only path to a warning.

    ``ALLOW_WITH_WARNING`` is the record that something was withheld; if any
    other combination could produce it, the field would stop meaning that.
    """
    engine = DefaultPolicyEngine()
    result = engine.evaluate(
        [_finding(PIICategory.PERSON_NAME)],
        _context(PIIDestination.EXTERNAL_LLM, redaction_available=True),
    )
    assert result.actions[PIICategory.PERSON_NAME] is PIIAction.REDACT
    assert result.decision is PIIDecision.ALLOW_WITH_WARNING
    assert result.warnings


def test_escalation_to_review_does_not_lower_the_risk_level():
    """Risk is a property of the data; the decision is about handling."""
    engine = DefaultPolicyEngine()
    result = engine.evaluate(
        [_finding(PIICategory.SNILS)],
        _context(PIIDestination.EXTERNAL_LLM, redaction_available=False),
    )
    assert result.decision is PIIDecision.REVIEW
    assert result.risk_level is PIIRiskLevel.HIGH


# --- decision precedence ---------------------------------------------------


def test_risk_order_is_the_declared_ladder_not_the_string_order():
    """The trap this map exists for, asserted so it cannot be removed.

    ``PIIRiskLevel`` is a ``str`` enum, so ``max()`` over two members compares
    their values alphabetically and orders them
    ``critical < high < low < medium``. A ``max`` without the rank map therefore
    reports a passport as ``LOW`` — an artifact-only bug, which is the worst kind
    to ship.
    """
    assert RISK_ORDER == (
        PIIRiskLevel.LOW,
        PIIRiskLevel.MEDIUM,
        PIIRiskLevel.HIGH,
        PIIRiskLevel.CRITICAL,
    )
    assert sorted(RISK_ORDER, key=str) != list(RISK_ORDER), (
        "if the values ever happen to sort in ladder order the rank map is dead code — "
        "re-derive it from the enum instead of keeping the ladder declared twice"
    )
    assert len(set(RISK_ORDER)) == len(RISK_ORDER) == len(PIIRiskLevel)


def test_precedence_order_is_block_review_warning_allow():
    """Each rung must win over every rung below it, in one document.

    Written as a ladder of *shrinking* finding sets rather than a matrix, so each
    assertion states one claim: a document that could block, blocks; one that
    could only warn, warns; one that can do neither, allows.
    """
    engine = DefaultPolicyEngine()
    external = _context(PIIDestination.EXTERNAL_LLM, redaction_available=True)

    blocking = [
        _finding(PIICategory.SECRET),
        _finding(PIICategory.PERSON_NAME),
        _finding(PIICategory.DOCTOR_NAME),
    ]
    assert engine.evaluate(blocking, external).decision is PIIDecision.BLOCK

    warning_only = [
        _finding(PIICategory.PERSON_NAME),  # redacted when redaction is available
        _finding(PIICategory.DOCTOR_NAME),  # allowed everywhere
    ]
    assert engine.evaluate(warning_only, external).decision is PIIDecision.ALLOW_WITH_WARNING

    review_only = [
        _finding(PIICategory.PERSON_NAME),
        _finding(PIICategory.DOCTOR_NAME),
    ]
    assert engine.evaluate(review_only, _context(PIIDestination.EXTERNAL_LLM)).decision is (
        PIIDecision.REVIEW
    )
    assert engine.evaluate(review_only, _context(PIIDestination.UNKNOWN)).decision is (
        PIIDecision.REVIEW
    )

    allowing = [_finding(PIICategory.DOCTOR_NAME)]
    assert engine.evaluate(allowing, external).decision is PIIDecision.ALLOW
    assert engine.evaluate(allowing, _context()).decision is PIIDecision.ALLOW


def test_one_secret_in_a_hundred_findings_still_blocks():
    engine = DefaultPolicyEngine()
    findings = [_finding(PIICategory.EMAIL) for _ in range(100)]
    findings.append(_finding(PIICategory.SECRET))
    result = engine.evaluate(findings, _context())
    assert result.decision is PIIDecision.BLOCK
    assert len(result.actions) == 2, "actions are per category, not per finding"


def test_a_warn_action_reduces_to_allow_with_warning():
    """The ladder's fourth rung is reachable only through a table that says WARN."""
    engine = DefaultPolicyEngine(
        DEFAULT_POLICY.model_copy(
            update={
                "rules": {
                    **DEFAULT_POLICY.rules,
                    PIICategory.GENDER: PIIRule(action=PIIAction.WARN, risk_level=PIIRiskLevel.LOW),
                }
            }
        )
    )
    result = engine.evaluate([_finding(PIICategory.GENDER)], _context())
    assert result.actions[PIICategory.GENDER] is PIIAction.WARN
    assert result.decision is PIIDecision.ALLOW_WITH_WARNING


# --- the actions map is post-override, post-escalation ---------------------


def test_the_returned_actions_are_what_the_decision_was_derived_from():
    """A caller acting on ``REDACT`` must not have to re-derive the escalation."""
    engine = DefaultPolicyEngine()
    result = engine.evaluate(
        [_finding(PIICategory.EMAIL), _finding(PIICategory.ORGANIZATION_NAME)],
        _context(PIIDestination.EXTERNAL_LLM, redaction_available=False),
    )
    assert result.actions[PIICategory.EMAIL] is PIIAction.REVIEW
    assert result.actions[PIICategory.ORGANIZATION_NAME] is PIIAction.ALLOW
    assert result.decision is PIIDecision.REVIEW


def test_the_engine_is_injectable_and_stateless():
    """Two evaluations of the same input agree; the table is the only state."""
    engine = DefaultPolicyEngine()
    context = _context(PIIDestination.EXTERNAL_LLM)
    findings = [_finding(PIICategory.SNILS)]
    assert engine.evaluate(findings, context) == engine.evaluate(findings, context)
