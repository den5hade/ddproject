"""M5 Phase 13 accept criterion: the manifest's ``expected_*`` are **measured**.

Before Phase 13 these fields were a specification nothing could check. M4 wrote
three synthetic fixtures and declared what the gate ought to find, and no test
compared the declaration to reality, because there was no detector to compare it
to. That is the honest state M4 recorded — and it is also the state in which a
manifest can rot into fiction without anything noticing. This module is what
closes it: every entry is scanned through the real
:func:`~app.pii.gate.build_document_gate` chain, and the categories, the decision
and the risk level must match **exactly**.

Equality, not containment
-------------------------

A subset assertion (``expected <= detected``) is the shape a test suite reaches
for when it wants to be robust, and it is the wrong shape here: it cannot fail
when a detector starts inventing categories, and an invented category is a wrong
masked value in a persisted artifact. The manifest is the ground truth a reviewer
checks an artifact against, so a finding that the manifest does not name is a
disagreement to resolve, not a bonus to accept.

The cost of equality is that every recall improvement shows up as a red test. That
is the point: the fix is to record the newly-observed behaviour in the manifest,
where the diff is visible to whoever reviews it, instead of letting the file drift
away from the code that is supposed to implement it.

Where the expectations are measured
-----------------------------------

``expected_decision`` is boundary-dependent — the same findings are
``ALLOW_WITH_WARNING`` at an internal destination, ``ALLOW`` where a redactor
exists, and ``REVIEW`` where a redaction is required and unavailable — and
plan §4.10 fixes the entry keys without a ``destination`` field. The manifest's
``notes`` therefore name the context, and this module constructs exactly that
one: ``EXTERNAL_LLM`` with ``redaction_available=False``, the fail-closed
direction. :func:`test_every_fixture_is_also_allow_at_the_production_boundary`
covers the other end of the same axis, so the two boundaries cannot be confused
for one another.

Detection is read from the gate's own detector and aggregator, and the decision
from the gate's own policy engine, so a fixture is never scored by a private
helper that could drift from the pipeline's wiring.
"""

from __future__ import annotations

import pytest
from app.classification.normalize import MarkdownNormalizer
from app.config.settings import Settings
from app.pii import build_document_gate
from app.pii.fixtures import PIIFixture, iter_pii_fixtures
from app.pii.gate import REDACTION_AVAILABLE
from app.pii.models import (
    PIICategory,
    PIIDecision,
    PIIDestination,
    PIIFinding,
    PIIRiskLevel,
    PIIScanStage,
)
from app.pii.policy import build_policy_context, resolve_destination

FIXTURES = iter_pii_fixtures()
SETTINGS = Settings(_env_file=None, pii_fingerprint_secret="manifest-verification-secret")

# The context the manifest's notes declare, built once: it is a test constant in
# the sense that matters — a value both the notes and the expectations are
# written against — so it is named rather than inlined at four call sites.
MANIFEST_CONTEXT = build_policy_context(
    SETTINGS,
    stage=PIIScanStage.DOCUMENT,
    destination=PIIDestination.EXTERNAL_LLM,
    redaction_available=False,
)
# Derived, not restated: the pipeline resolves its destination from
# `Settings.llm_mode` (Phase 15), so the "production boundary" is a fact about
# configuration. Pinning the literal here would let the two drift and this
# fixture suite would keep passing against a boundary the worker no longer uses.
PRODUCTION_CONTEXT = build_policy_context(
    SETTINGS,
    stage=PIIScanStage.DOCUMENT,
    destination=resolve_destination(SETTINGS),
    redaction_available=REDACTION_AVAILABLE,
)

GATE = build_document_gate(SETTINGS)
IDS = [fixture.file for fixture in FIXTURES]


def _scan(markdown: str) -> list[PIIFinding]:
    """Detect and aggregate exactly as the pipeline does, then decide.

    The document gate's ``inspect`` builds its own policy context from settings,
    so it cannot be asked about another boundary; the detector chain and the
    policy engine it is assembled from can, and they are the components under
    test. Everything between them — normalization, aggregation, risk, precedence
    — is the production wiring, not a reimplementation of it.
    """
    document = MarkdownNormalizer().normalize(markdown, metadata={})
    findings = GATE.aggregator.aggregate(GATE.detector.detect(document))
    return findings


def _decided(markdown: str, context=MANIFEST_CONTEXT):
    return GATE.policy_engine.evaluate(_scan(markdown), context)


# --- the criterion --------------------------------------------------------


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_every_declared_category_is_found_and_nothing_else(fixture: PIIFixture):
    found = {finding.category.value for finding in _scan(fixture.path.read_text(encoding="utf-8"))}
    assert found == set(fixture.expected_categories), (
        f"{fixture.file}: the chain and the manifest disagree.\n"
        f"  declared: {sorted(fixture.expected_categories)}\n"
        f"  found:    {sorted(found)}\n"
        f"  only in the manifest: {sorted(set(fixture.expected_categories) - found)}\n"
        f"  only in the chain:    {sorted(found - set(fixture.expected_categories))}"
    )


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_every_declared_decision_and_risk_level_is_the_one_reached(fixture: PIIFixture):
    result = _decided(fixture.path.read_text(encoding="utf-8"))
    assert result.decision.value == fixture.expected_decision
    assert result.risk_level.value == fixture.expected_risk_level


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_the_scan_result_is_boundary_safe(fixture: PIIFixture):
    """Whatever the verdict, the projection carries no value and no fingerprint.

    Run per fixture so the leak test is about *these documents* rather than about
    one representative of them: a new entry that somehow bypassed
    :meth:`DefaultPIIGate._project` would otherwise be covered only by whatever
    the shared-path tests happened to include.
    """
    from app.pii.models import PIIScanResult

    result = PIIScanResult.model_validate(
        GATE._project(_decided(fixture.path.read_text(encoding="utf-8")),
                      _scan(fixture.path.read_text(encoding="utf-8")),
                      MANIFEST_CONTEXT).model_dump()
    )
    for finding in result.findings:
        assert "value" not in finding.model_dump()
        assert "value_fingerprint" not in finding.model_dump()
        assert finding.masked_value


# --- the boundary the expectations do NOT describe -----------------------


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_every_fixture_is_also_allow_at_the_production_boundary(fixture: PIIFixture):
    """The production context today, for the same fixtures.

    The manifest describes the fail-closed boundary because that is the one that
    distinguishes the three decisions. The pipeline does not use it: it scans
    with ``INTERNAL_LLM`` and a working redactor, where the base policy issues
    ``ALLOW`` for everything but a credential. Asserting it here means a change
    to the default boundary shows up in the fixture suite rather than in a
    production incident — and it is the assertion that would fail if
    ``REDACTION_AVAILABLE`` or ``DEFAULT_DESTINATION`` moved, since the two
    contexts would then be the same context under two names.
    """
    result = _decided(fixture.path.read_text(encoding="utf-8"), PRODUCTION_CONTEXT)
    expected = (
        PIIDecision.BLOCK.value
        if PIICategory.SECRET.value in fixture.expected_categories
        else PIIDecision.ALLOW.value
    )
    assert result.decision.value == expected
    # Risk does not depend on the boundary, so it must not have moved.
    assert result.risk_level.value == fixture.expected_risk_level


def test_only_a_credential_blocks_at_every_boundary():
    """The distinction the whole policy table exists to draw.

    A patient identifier and a leaked API key produce the same *kind* of
    finding — a category with a risk level — and only one of them stops the
    document. If a future policy change made a patient identifier block, the
    per-fixture tests would report a decision mismatch and nothing would say
    *why* that is alarming; this says it in one line.
    """
    patient = next(f for f in FIXTURES if f.file.startswith("patient/"))
    malicious = next(f for f in FIXTURES if f.contains_secret)

    for context in (MANIFEST_CONTEXT, PRODUCTION_CONTEXT):
        patient_result = _decided(patient.path.read_text(encoding="utf-8"), context)
        malicious_result = _decided(malicious.path.read_text(encoding="utf-8"), context)
        assert patient_result.decision is not PIIDecision.BLOCK
        assert malicious_result.decision is PIIDecision.BLOCK


# --- the Phase 13 acceptance pair, called out by name ---------------------


def test_the_declined_appointment_yields_exactly_person_name_and_ticket_number():
    """Phase 13's accept criterion, verbatim, as a test anyone can read.

    The document is a **declined** booking reproducing the real ``2b8fdd0d``
    registration marker's shape with invented values, and its name is the
    declined genitive form of §7 gotcha G1 — ``для пациента Кузнецова
    Александра Петровича``, mid-sentence, no colon, no capital to lean on. That
    is the shape a nominative ``ФИО`` pattern cannot match, and it is the one
    the gate exists to catch, so the category set is asserted in full rather than
    as a subset: the doctor name in the same row set, the service date, the
    specialty and the cabinet number are all present in the fixture as
    near-misses, and each of them staying *out* of the result is the test.
    """
    appointment = next(f for f in FIXTURES if f.file.startswith("appointment/"))
    found = {
        finding.category.value
        for finding in _scan(appointment.path.read_text(encoding="utf-8"))
    }

    assert found == {PIICategory.PERSON_NAME.value, PIICategory.TICKET_NUMBER.value}


def test_the_declined_name_is_found_in_its_genitive_prose_form():
    """The G1 leak itself, on the contour that leaks it.

    ``for пациента X Y Z`` is the canonical payload's shape, and it is *not* the
    document contour: the canonical guard (Phase 14) scans un-folded payload
    leaves, where capitalisation is still there. Both rules are named here so a
    regression in either one is attributed to the rule that broke — the
    three-token rule is the general catch, the label rule the construction-aware
    one, and Phase 9's tripwire is the label rule alone.
    """
    from app.pii.detectors import PatternPIIDetector

    detector = PatternPIIDetector(fingerprint_secret=SETTINGS.pii_fingerprint_secret)
    leaked = "Электронная запись на прием для пациента Кузнецова Александра Петровича."
    found = detector.detect_text(leaked)

    names = [f for f in found if f.category is PIICategory.PERSON_NAME]
    assert names, "G1: a declined, genitive, mid-sentence name is not PII any more"
    assert {f.value.casefold() for f in names} == {"кузнецова александра петровича"}
    assert any(f.detector.endswith("person_name.three_token") for f in names)
    assert any(f.detector.endswith("person_name.after_label") for f in names)


def test_prose_after_a_patient_label_is_not_a_person_name():
    """The regression that the declined-name fix had to avoid buying.

    Making the label rule construction-aware could have been done by widening it,
    and the first version of the appointment fixture is what that looked like:
    ``Пациент отказался от приёма`` came back as the person name
    ``отказался от приёма`` at 0.7. Over-masking a clause is a fidelity problem
    rather than a leak, but it is a problem the fixture set exists to catch, and
    a rule that cannot tell a name from a verb is a rule that will.
    """
    from app.pii.detectors import PatternPIIDetector

    detector = PatternPIIDetector(fingerprint_secret=SETTINGS.pii_fingerprint_secret)
    for text in (
        "Пациент отказался от приёма. Персональные данные не сохранены.",
        "Пациент отказался",
        "у пациента с повышенным давлением",
    ):
        names = [f for f in detector.detect_text(text) if f.category is PIICategory.PERSON_NAME]
        assert names == [], (text, [(f.value, f.detector) for f in names])


# --- the false positive the manifest records rather than hides -----------


def test_the_manifest_names_the_known_ticket_false_positive():
    """A recorded false positive is information; an unnamed one is a bug report
    waiting to be filed against a detector that is behaving as documented.

    The 28-digit API key in ``malicious/synthetic-injection-01.md`` is one
    unbroken digit run, and ``pattern.ticket_number.long_digits`` claims any run
    of twelve or more. The manifest says so, this test makes sure it keeps
    saying so, and the two together mean a reader comparing an artifact to the
    ground truth finds the explanation already in the file.
    """
    malicious = next(f for f in FIXTURES if f.contains_secret)
    assert PIICategory.TICKET_NUMBER.value in malicious.expected_categories
    assert PIICategory.SECRET.value in malicious.expected_categories

    key = next(
        finding
        for finding in _scan(malicious.path.read_text(encoding="utf-8"))
        if finding.category is PIICategory.TICKET_NUMBER
    )
    assert len(key.value) >= 28
    assert "sk-live" not in key.value


# --- what the risk levels are allowed to be ------------------------------


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_risk_is_the_highest_of_the_findings_present(fixture: PIIFixture):
    """A risk level that is not derived from the findings is a hand-written
    number, and a hand-written number is a number nobody recomputes.

    The policy engine is the only source, so this recomputes the maximum over
    the fixture's own findings and compares — through :data:`RISK_ORDER`, not
    ``max()`` over the levels themselves, because ``PIIRiskLevel`` is a ``str``
    enum and ``max(low, high)`` returns ``"low"``. That trap is the reason the
    ladder exists at all; a test that reintroduced it would agree with the engine
    for the wrong reason on some documents and fail on others, and the
    difference is invisible in the diff.

    The value of the test is prospective: it holds for all four fixtures today,
    and stops holding if a risk level is edited in a manifest without a matching
    change in the table.
    """
    from app.pii.policy import DEFAULT_POLICY, RISK_ORDER

    findings = _scan(fixture.path.read_text(encoding="utf-8"))
    if not findings:
        assert fixture.expected_risk_level == PIIRiskLevel.LOW.value
        return
    rank = {level: position for position, level in enumerate(RISK_ORDER)}
    highest = max(
        (DEFAULT_POLICY.risk_for(finding.category) for finding in findings),
        key=rank.__getitem__,
    )
    assert fixture.expected_risk_level == highest.value
