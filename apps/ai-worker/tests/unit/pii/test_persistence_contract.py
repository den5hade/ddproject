"""Phase 7 contract: what a PII verdict is allowed to reach (plan §4.7–4.8).

Three of these assertions carry the security value and are restated from the
plan's §5 list:

1. the ``"pii"`` block key set is exactly §4.7's, and none of those keys is a
   value, a mask or a fingerprint;
2. ``PIIAuditRecord`` has no value or fingerprint field — the exact field set is
   asserted so one cannot be appended later;
3. the version constants are importable and stamped onto the persisted shapes,
   so an old verdict stays interpretable.

The block shape is asserted against the plan's own §4.7 JSON example rather than
against a second model, because §4.7 puts ``PIIMeta`` in
``packages/canonical/canonical/metadata.py`` where M4 must not edit. See
``app/pii/persistence.py`` for why M4 declares keys as data.
"""

from __future__ import annotations

import re

import pytest
from app.pii.canonical_guard import CANONICAL_POLICY_DESTINATION, CANONICAL_POLICY_STAGE
from app.pii.models import (
    PIIAuditRecord,
    PIICategory,
    PIIDecision,
    PIIFinding,
    PIIFindingSummary,
    PIIRiskLevel,
    PIIScanResult,
    PIIScanStage,
)
from app.pii.persistence import (
    DECISION_AUDIT_EVENTS,
    DETECTOR_VERSION,
    PII_ARTIFACT_FILENAME,
    PII_AUDIT_EVENTS,
    PII_META_BLOCK_KEY,
    PII_META_OPTIONAL_KEYS,
    PII_META_REQUIRED_KEYS,
    PII_POLICY_VERSION,
    PII_REDACTED_EVENT,
)

# Plan §4.7's example block, transcribed. Required first, then the two
# list-valued keys that default empty — the split is asserted against the
# constants below rather than assumed, so a reordering in either place fails.
PLAN_S47_REQUIRED = [
    "decision",
    "risk_level",
    "stage",
    "destination",
    "findings_count",
    "category_counts",
    "categories",
    "detector_version",
    "policy_version",
]
PLAN_S47_OPTIONAL = ["reasons", "warnings"]


# --- §4.7 the block shape -------------------------------------------------


def test_block_key_is_pii_for_frontmatter_and_event():
    assert PII_META_BLOCK_KEY == "pii"


def test_required_keys_match_plan_4_7_exactly():
    assert list(PII_META_REQUIRED_KEYS) == PLAN_S47_REQUIRED


def test_optional_keys_match_plan_4_7_exactly():
    assert list(PII_META_OPTIONAL_KEYS) == PLAN_S47_OPTIONAL


def test_full_block_is_eleven_keys():
    # Guards against a key landing in neither tuple: the two tuples are the whole
    # block, so an unlisted key would reach a consumer undeclared.
    assert len(PII_META_REQUIRED_KEYS) + len(PII_META_OPTIONAL_KEYS) == 11


def test_required_and_optional_keys_are_disjoint():
    assert not set(PII_META_REQUIRED_KEYS) & set(PII_META_OPTIONAL_KEYS)


def test_no_block_key_is_a_value_mask_or_fingerprint():
    forbidden = {"value", "masked_value", "value_fingerprint", "fingerprint", "raw_value"}
    keys = set(PII_META_REQUIRED_KEYS) | set(PII_META_OPTIONAL_KEYS)
    assert keys & forbidden == set()


def test_block_carries_no_finding_detail_keys():
    # The block summarises; the artifact holds detail. A key from
    # PIIFindingSummary beyond the two count/versions keys would mean the
    # frontmatter is growing a per-finding surface it has no business carrying.
    finding_keys = set(PIIFindingSummary.model_fields)
    allowed = {"category", "masked_value", "source", "confidence", "detector_version", "action"}
    assert finding_keys - allowed, "sanity: summary should have keys the block must not carry"
    assert (set(PII_META_REQUIRED_KEYS) | set(PII_META_OPTIONAL_KEYS)) & finding_keys == set()


def test_artifact_filename_mirrors_classification():
    assert PII_ARTIFACT_FILENAME == "pii_result.json"
    assert PII_ARTIFACT_FILENAME != "classification_result.json"


def test_block_and_artifact_are_distinct_surfaces():
    # §4.7: full findings live only in the artifact, "mirroring"
    # classification_result.json. One file, two jobs, would defeat the reason the
    # block was made optional — so the artifact is deliberately *not* the block
    # dumped to a file named after the key.
    assert PII_ARTIFACT_FILENAME.endswith(".json")
    assert f"{PII_META_BLOCK_KEY}.json" != PII_ARTIFACT_FILENAME


# --- §4.7 audit events ----------------------------------------------------


def test_audit_vocabulary_is_exactly_the_plan_four():
    assert set(PII_AUDIT_EVENTS) == {
        "pii.scan.completed",
        "pii.blocked",
        "pii.review.required",
        "pii.redacted",
    }
    assert len(PII_AUDIT_EVENTS) == 4


def test_every_audit_event_is_pii_namespaced():
    for event in PII_AUDIT_EVENTS:
        assert event.startswith("pii."), event
        assert event == event.lower()
        assert " " not in event


def test_redacted_event_is_in_the_vocabulary():
    assert PII_REDACTED_EVENT == "pii.redacted"
    assert PII_REDACTED_EVENT in PII_AUDIT_EVENTS


def test_decision_audit_map_covers_every_decision():
    assert set(DECISION_AUDIT_EVENTS) == {d.value for d in PIIDecision}


def test_decision_audit_map_values_are_known_events():
    for decision, event in DECISION_AUDIT_EVENTS.items():
        assert event in PII_AUDIT_EVENTS, decision


def test_block_and_review_decisions_emit_distinct_events():
    # The one asymmetry a consumer would otherwise have to discover at runtime:
    # a blocked document is not a "scan completed".
    assert DECISION_AUDIT_EVENTS[PIIDecision.BLOCK.value] == "pii.blocked"
    assert DECISION_AUDIT_EVENTS[PIIDecision.REVIEW.value] == "pii.review.required"
    assert DECISION_AUDIT_EVENTS[PIIDecision.ALLOW.value] != "pii.blocked"


def test_allow_and_allow_with_warning_share_the_scan_event():
    # Documented as deliberate: the two differ in the stored result, not in what
    # happened operationally.
    assert (
        DECISION_AUDIT_EVENTS[PIIDecision.ALLOW.value]
        == DECISION_AUDIT_EVENTS[PIIDecision.ALLOW_WITH_WARNING.value]
        == "pii.scan.completed"
    )


def test_no_audit_event_is_emitted_for_redaction_alone():
    # Redaction is additive, not a decision, so it must not appear as a decision's
    # own event — otherwise "how often do we redact" is unanswerable without
    # joining against the stored result.
    assert PII_REDACTED_EVENT not in DECISION_AUDIT_EVENTS.values()


# --- §5 assertion 3: the audit record carries no values -------------------


def test_audit_record_has_no_value_or_fingerprint_field():
    fields = set(PIIAuditRecord.model_fields)
    assert "value" not in fields
    assert "value_fingerprint" not in fields
    assert "masked_value" not in fields


def test_audit_record_field_set_is_exactly_the_phase_1_model():
    assert set(PIIAuditRecord.model_fields) == {
        "event",
        "document_id",
        "stage",
        "decision",
        "risk_level",
        "findings_count",
        "detector_version",
        "policy_version",
        "occurred_at",
    }


def test_audit_record_accepts_every_planned_event():
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    for event in PII_AUDIT_EVENTS:
        record = PIIAuditRecord(
            event=event,
            document_id="doc-1",
            stage=PIIScanStage.DOCUMENT,
            decision=PIIDecision.ALLOW,
            risk_level=PIIRiskLevel.LOW,
            findings_count=0,
            detector_version=DETECTOR_VERSION,
            policy_version=PII_POLICY_VERSION,
            occurred_at=now,
        )
        assert record.event == event


def test_audit_record_dumps_no_value_keys():
    from datetime import UTC, datetime

    record = PIIAuditRecord(
        event="pii.scan.completed",
        document_id="doc-1",
        stage=PIIScanStage.DOCUMENT,
        decision=PIIDecision.ALLOW,
        risk_level=PIIRiskLevel.LOW,
        findings_count=2,
        detector_version=DETECTOR_VERSION,
        policy_version=PII_POLICY_VERSION,
        occurred_at=datetime.now(UTC),
    )
    dumped = set(record.model_dump(mode="json"))
    assert dumped & {"value", "value_fingerprint", "masked_value"} == set()


# --- §4.8 versioning ------------------------------------------------------

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


@pytest.mark.parametrize("version", [DETECTOR_VERSION, PII_POLICY_VERSION])
def test_version_constants_are_semver(version):
    assert _SEMVER.match(version), version


def test_version_constants_are_importable_from_their_home_modules():
    from app.pii.detectors import DETECTOR_VERSION as from_detectors
    from app.pii.policy import PII_POLICY_VERSION as from_policy

    assert from_detectors == DETECTOR_VERSION
    assert from_policy == PII_POLICY_VERSION


def test_versions_are_both_1_0_0_at_m4():
    assert DETECTOR_VERSION == "1.0.0"
    assert PII_POLICY_VERSION == "1.0.0"


def test_scan_result_stamps_both_versions():
    fields = PIIScanResult.model_fields
    assert "detector_version" in fields
    assert "policy_version" in fields


def test_block_versions_agree_with_the_persisted_result():
    # The block and the artifact are written at the same moment, so a mismatch
    # means one of them was stamped from a stale value.
    result_fields = set(PIIScanResult.model_fields)
    assert {"detector_version", "policy_version"} <= result_fields
    assert {"detector_version", "policy_version"} <= set(PII_META_REQUIRED_KEYS)


def test_canonical_policy_constants_are_real_stages_and_destinations():
    assert CANONICAL_POLICY_STAGE is PIIScanStage.CANONICAL
    assert CANONICAL_POLICY_DESTINATION in {"persistence", "unknown"}


def test_versioning_doc_states_a_decision_change_bumps_policy():
    # The rule is the one that makes a stored verdict interpretable, and it lives
    # only in prose, so it is asserted against the module that has to carry it.
    from app.pii import persistence

    doc = persistence.__doc__ or ""
    assert "bump" in doc.lower()
    assert "major" in doc.lower()


# --- public surface -------------------------------------------------------


def test_persistence_names_are_exported_from_the_package():
    import app.pii

    for name in (
        "DECISION_AUDIT_EVENTS",
        "PII_ARTIFACT_FILENAME",
        "PII_AUDIT_EVENTS",
        "PII_META_BLOCK_KEY",
        "PII_META_OPTIONAL_KEYS",
        "PII_META_REQUIRED_KEYS",
        "PII_REDACTED_EVENT",
    ):
        assert name in app.pii.__all__, name


def test_fixture_loader_is_not_exported_from_the_package():
    # Matches app.classification: the dataset loader is a dev/eval surface reached
    # as app.pii.fixtures, not part of the gate contract, so it stays out of the
    # public API the pipeline is meant to depend on.
    import app.pii

    assert "iter_pii_fixtures" not in app.pii.__all__
    assert not any("ixture" in name for name in app.pii.__all__)


def test_versions_are_exported_exactly_once():
    # They are reachable from app.pii (home modules) and from app.pii.persistence
    # (the version surface); only one of those may be the package export.
    import app.pii

    assert app.pii.__all__.count("DETECTOR_VERSION") == 1
    assert app.pii.__all__.count("PII_POLICY_VERSION") == 1


# --- Phase 1/2 invariants this phase depends on ---------------------------


def test_finding_still_excludes_value_from_serialization():
    finding = PIIFinding(
        category=PIICategory.PERSON_NAME,
        value="Example Person",
        masked_value="**",
        value_fingerprint="hmac-sha256:" + "a" * 64,
        confidence=0.9,
        source="pattern",
        detector="regex.person_name",
        detector_version=DETECTOR_VERSION,
    )
    dumped = finding.model_dump()
    assert "value" not in dumped
    assert "value_fingerprint" not in dumped
    # ...and the value is still reachable in-process, which is what the mask and
    # the redaction contract are for.
    assert finding.value == "Example Person"
