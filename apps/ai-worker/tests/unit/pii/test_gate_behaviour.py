"""The Phase 9 acceptance test: ``await gate.inspect(...)`` end to end.

This is the first vertical slice in M5, so it is also the first test that runs
the whole chain — detector, aggregator, policy engine, projection — and the first
that produces a real :class:`~app.pii.models.PIIScanResult` rather than asserting
a contract shape.

The two claims the plan makes for this phase are both here:

1. the ``synthetic-consultation-01`` fixture's scan matches the manifest's
   declared ``expected_decision`` and ``expected_risk_level`` — ground truth M4
   could only *state*, because nothing detected;
2. the result dumps with no ``value`` key at any depth.

The second is walked recursively rather than checked on the top level, because
the leak this milestone exists to close is a nested one: the real document's name
reached ``fields.note``, three consumers deep.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from app.classification.normalize import MarkdownNormalizer
from app.config.settings import Settings
from app.pii import (
    DETECTOR_VERSION,
    PII_POLICY_VERSION,
    CompositePIIDetector,
    DefaultPIIAggregator,
    DefaultPIIGate,
    DefaultPolicyEngine,
    PatternPIIDetector,
    PIICategory,
    PIIDecision,
    PIIDecisionError,
    PIIDestination,
    PIIRiskLevel,
    PIIScanResult,
    PIIScanStage,
    build_policy_context,
)
from app.pii.fixtures import iter_pii_fixtures
from app.pii.policy import PIIPolicyContext

SECRET = "phase-9-acceptance-test-secret"

FIXTURE = next(f for f in iter_pii_fixtures() if f.file.endswith("synthetic-consultation-01.md"))
"""The manifest entry the plan names as Phase 9's acceptance fixture."""


def _context_builder(destination: PIIDestination):
    settings = Settings(pii_fingerprint_secret=SECRET)

    def builder(document, context) -> PIIPolicyContext:
        return build_policy_context(settings, stage=PIIScanStage.DOCUMENT, destination=destination)

    return builder


def _gate(destination: PIIDestination = PIIDestination.EXTERNAL_LLM) -> DefaultPIIGate:
    detector = CompositePIIDetector([PatternPIIDetector(fingerprint_secret=SECRET)])
    return DefaultPIIGate(
        detector=detector,
        aggregator=DefaultPIIAggregator(),
        policy_engine=DefaultPolicyEngine(),
        policy_context_builder=_context_builder(destination),
    )


def _document(markdown: str):
    """A real normalized document — not a stand-in.

    The point of using the production normalizer is that its ``raw_text`` is
    case-folded, which is the input the pattern rules actually face in the
    pipeline. A stand-in carrying capitalised prose would let a name rule that
    cannot see folded text pass this whole file.
    """
    return MarkdownNormalizer().normalize(markdown)


async def _scan(
    fixture=FIXTURE,
    destination: PIIDestination = PIIDestination.EXTERNAL_LLM,
) -> PIIScanResult:
    """``gate.inspect`` over a fixture's real markdown, normalized as production does."""
    markdown = fixture.path.read_text(encoding="utf-8")
    return await _gate(destination).inspect(_document(markdown), _processing_context())


def _processing_context():
    return SimpleNamespace(
        document_id=FIXTURE.path.stem,
        document_version_id="v1",
        patient_id="p-1",
        client_type="web",
        processing_id="proc-1",
        attributes={},
    )


def _walk_keys(node) -> set[str]:
    """Every mapping key anywhere in a serialized structure."""
    keys: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            keys.add(key)
            keys |= _walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            keys |= _walk_keys(item)
    return keys


# --- acceptance -------------------------------------------------------------


@pytest.mark.asyncio
async def test_inspect_matches_the_manifests_declared_decision_and_risk():
    """M4 declared this fixture's expectations; Phase 9 confirms them.

    ``EXTERNAL_LLM`` is the context the manifest's own notes assume, and it is
    the interesting one: redaction is required and (Phase 9 has no redactor) not
    available, so the expected ``review`` is the *escalation* path rather than a
    plain verdict. A test that ran this at ``INTERNAL_LLM`` would assert
    ``allow`` and prove nothing about the policy.
    """
    result = await _scan()

    assert isinstance(result, PIIScanResult)
    assert result.decision.value == FIXTURE.expected_decision
    assert result.risk_level.value == FIXTURE.expected_risk_level
    assert result.stage is PIIScanStage.DOCUMENT
    assert result.destination is PIIDestination.EXTERNAL_LLM


@pytest.mark.asyncio
async def test_inspect_dumps_with_no_value_key_at_any_depth():
    """The security assertion of the whole milestone, walked recursively.

    ``PIIScanResult`` and ``PIIFindingSummary`` have no ``value`` field *at all*
    (Phase 1), so this is true by construction — which is exactly why it is worth
    asserting against the real dump rather than against ``model_fields``: a future
    ``metadata`` addition is the one place a raw value could reappear.
    """
    result = await _scan()
    dumped = json.loads(result.model_dump_json())

    assert "value" not in _walk_keys(dumped)
    assert "value_fingerprint" not in _walk_keys(dumped)
    assert not any("sha256" in str(value) for value in _walk_keys(dumped))


@pytest.mark.asyncio
async def test_inspect_reports_no_patient_name_in_the_persisted_text():
    """The mask, not the value — and no substring of the real name anywhere."""
    markdown = FIXTURE.path.read_text(encoding="utf-8")
    result = await _gate().inspect(_document(markdown), _processing_context())
    body = result.model_dump_json()

    for token in ("Смирнова", "Ольга", "Ивановна", "smirnova", "1974-03-12", "000-11-22"):
        assert token not in body, f"{token!r} reached the scan result"


# --- the shape of a real result --------------------------------------------


@pytest.mark.asyncio
async def test_result_carries_the_versions_and_consistent_counts():
    result = await _scan()
    assert result.detector_version == DETECTOR_VERSION
    assert result.policy_version == PII_POLICY_VERSION
    assert result.findings_count == len(result.findings)
    assert sum(result.category_counts.values()) == len(result.findings)
    assert set(result.category_counts) <= {f.category.value for f in result.findings}
    assert result.processed_at.tzinfo is not None, "an audit timestamp must be unambiguous"


@pytest.mark.asyncio
async def test_every_summary_is_masked_and_never_carries_a_value():
    result = await _scan()
    assert result.findings
    for summary in result.findings:
        assert summary.masked_value
        assert "value" not in type(summary).model_fields
        assert type(summary).model_fields.keys() <= {
            "category",
            "masked_value",
            "confidence",
            "source",
            "detector",
            "start",
            "end",
        }


@pytest.mark.asyncio
async def test_the_fixture_declares_categories_the_detector_can_produce():
    """Manifest expectations vs. what Phase 9 can actually see.

    Not an equality check: the manifest lists ``medical_record_number`` and
    ``doctor_name``, which belong to Phase 13's labelled detector (a 10-digit
    card number is deliberately not claimed by a digit-run rule, and a
    two-token ``Петров И. С.`` is a doctor). What must hold is that every
    expected category the detector does claim is correct, and that the categories
    it does claim are among those the manifest expects — a *new* category
    appearing in a real document is a finding the dataset has not blessed, and it
    belongs in the manifest before it belongs in production.
    """
    result = await _scan()
    expected = set(FIXTURE.expected_categories)
    found = {summary.category.value for summary in result.findings}

    assert found <= expected, f"undeclared categories in the manifest: {sorted(found - expected)}"
    assert PIICategory.PERSON_NAME.value in found
    assert PIICategory.EMAIL.value in found
    assert PIICategory.PHONE.value in found
    assert PIICategory.DATE_OF_BIRTH.value in found


# --- decisions through the gate --------------------------------------------


@pytest.mark.asyncio
async def test_a_clean_document_is_allow_at_low_with_no_findings():
    clean = next(f for f in iter_pii_fixtures() if f.file.startswith("clean/"))
    result = await _scan(clean)
    assert result.decision is PIIDecision.ALLOW
    assert result.risk_level is PIIRiskLevel.LOW
    assert result.findings == []
    assert result.findings_count == 0
    assert result.category_counts == {}


@pytest.mark.asyncio
async def test_the_same_document_decides_differently_per_destination():
    """One gate, two destinations — the difference is configuration, not code."""
    markdown = FIXTURE.path.read_text(encoding="utf-8")
    internal = await _gate(PIIDestination.INTERNAL_LLM).inspect(
        _document(markdown), _processing_context()
    )
    external = await _gate().inspect(_document(markdown), _processing_context())
    assert internal.decision is PIIDecision.ALLOW
    assert external.decision is PIIDecision.REVIEW
    assert internal.findings == external.findings, (
        "the destination changes the verdict, not the evidence"
    )


@pytest.mark.asyncio
async def test_a_secret_fixture_blocks_only_once_a_detector_sees_it():
    """Phase 9 has no secret detector, so the fixture is not yet blocked.

    Stated explicitly rather than asserted as ``BLOCK`` because the plan
    schedules the secret detector for Phase 13: this test is the tripwire that
    fails *loudly* if a later phase leaves the malicious fixture allowed.
    """
    malicious = next(f for f in iter_pii_fixtures() if f.file.startswith("malicious/"))
    result = await _scan(malicious)
    assert result.decision is not PIIDecision.BLOCK
    assert "sk-live-" not in result.model_dump_json()


# --- fail closed ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_gate_without_a_policy_context_fails_closed():
    """No context means no decision, and the answer is never ``ALLOW``."""
    gate = DefaultPIIGate(
        detector=CompositePIIDetector([PatternPIIDetector(fingerprint_secret=SECRET)]),
        aggregator=DefaultPIIAggregator(),
        policy_engine=DefaultPolicyEngine(),
        policy_context_builder=lambda document, context: None,
    )
    with pytest.raises(PIIDecisionError) as excinfo:
        await gate.inspect(_document("любой текст"), _processing_context())
    assert "destination" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_a_detector_without_a_secret_fails_closed():
    """The chain built without ``build_detector_chain`` still refuses to scan."""
    gate = DefaultPIIGate(
        detector=CompositePIIDetector([PatternPIIDetector()]),
        aggregator=DefaultPIIAggregator(),
        policy_engine=DefaultPolicyEngine(),
        policy_context_builder=_context_builder(PIIDestination.EXTERNAL_LLM),
    )
    with pytest.raises(Exception, match="(?i)fingerprint"):
        await gate.inspect(_document("СНИЛС 123-067-082 21"), _processing_context())  # noqa: B017
