"""Contract-level tests for PII gate domain types (M4 Phase 1).

Contract tests only: enum values, field shapes, defaults, ``extra="forbid"``
enforcement and the three structural "no raw PII" assertions. No detection
logic exists yet, so nothing here exercises behaviour (mirrors the
Classification M1 approach).
"""

from datetime import UTC, datetime

import app.pii
import pytest
from app.pii import (
    InvalidPIIInputError,
    PIIAction,
    PIIAuditRecord,
    PIICategory,
    PIIDecision,
    PIIDecisionError,
    PIIDecisionResult,
    PIIDestination,
    PIIDetectorError,
    PIIError,
    PIIFinding,
    PIIFindingSummary,
    PIIPolicyError,
    PIIRedactionError,
    PIIRiskLevel,
    PIIScanResult,
    PIIScanStage,
    PIISource,
)
from pydantic import ValidationError
from tests.support.pii_imports import (
    imports_forbidden_domains,
    imports_forbidden_infrastructure,
    pii_source_files,
    unexpected_type_only_imports,
)


def test_pii_category_values():
    assert PIICategory.PERSON_NAME == "person_name"
    assert PIICategory.DATE_OF_BIRTH == "date_of_birth"
    assert PIICategory.AGE == "age"
    assert PIICategory.GENDER == "gender"
    assert PIICategory.NATIONALITY == "nationality"
    assert PIICategory.EMAIL == "email"
    assert PIICategory.PHONE == "phone"
    assert PIICategory.ADDRESS == "address"
    assert PIICategory.PASSPORT == "passport"
    assert PIICategory.NATIONAL_ID == "national_id"
    assert PIICategory.INSURANCE_NUMBER == "insurance_number"
    assert PIICategory.SNILS == "snils"
    assert PIICategory.INN == "inn"
    assert PIICategory.PATIENT_ID == "patient_id"
    assert PIICategory.MEDICAL_RECORD_NUMBER == "medical_record_number"
    assert PIICategory.LAB_ORDER_ID == "lab_order_id"
    assert PIICategory.ENCOUNTER_ID == "encounter_id"
    assert PIICategory.TICKET_NUMBER == "ticket_number"
    assert PIICategory.DOCTOR_NAME == "doctor_name"
    assert PIICategory.DOCTOR_LICENSE == "doctor_license"
    assert PIICategory.ORGANIZATION_NAME == "organization_name"
    assert PIICategory.ORGANIZATION_ID == "organization_id"
    assert PIICategory.SECRET == "secret"
    assert len(PIICategory) == 23


def test_supporting_enum_values():
    assert [m.value for m in PIISource] == [
        "pattern",
        "structured_field",
        "ner",
        "llm",
        "canonical",
    ]
    assert [m.value for m in PIIRiskLevel] == ["low", "medium", "high", "critical"]
    assert [m.value for m in PIIAction] == [
        "allow",
        "warn",
        "redact",
        "review",
        "block",
    ]
    assert [m.value for m in PIIDecision] == [
        "allow",
        "allow_with_warning",
        "review",
        "block",
    ]
    assert [m.value for m in PIIDestination] == [
        "internal_llm",
        "external_llm",
        "persistence",
        "unknown",
    ]
    assert [m.value for m in PIIScanStage] == ["document", "canonical"]


def _minimal_finding() -> PIIFinding:
    return PIIFinding(
        category=PIICategory.PERSON_NAME,
        value="Шадеркин Денис Сергеевич",
        masked_value="Ш***** Д***** С*********",
        value_fingerprint="hmac-sha256:0f2c",
        confidence=0.97,
        source=PIISource.PATTERN,
        detector="pattern.person_name",
        detector_version="1.0.0",
    )


def test_finding_defaults_and_required_fields():
    finding = _minimal_finding()
    assert finding.start is None
    assert finding.end is None
    assert finding.metadata == {}
    for field in (
        "category",
        "value",
        "masked_value",
        "value_fingerprint",
        "confidence",
        "source",
        "detector",
        "detector_version",
    ):
        assert field in PIIFinding.model_fields


def test_finding_is_frozen():
    finding = _minimal_finding()
    with pytest.raises(ValidationError):
        finding.confidence = 0.1


def test_finding_forbids_extra_fields():
    with pytest.raises(ValidationError):
        PIIFinding(
            category=PIICategory.AGE,
            value="39",
            masked_value="**",
            value_fingerprint="hmac-sha256:aa11",
            confidence=0.5,
            source=PIISource.PATTERN,
            detector="pattern.age",
            detector_version="1.0.0",
            unexpected=True,
        )  # type: ignore[call-arg]


def _minimal_summary() -> PIIFindingSummary:
    return PIIFindingSummary(
        category=PIICategory.PERSON_NAME,
        masked_value="Ш***** Д***** С*********",
        confidence=0.97,
        source=PIISource.PATTERN,
        detector="pattern.person_name",
    )


def test_finding_summary_defaults():
    summary = _minimal_summary()
    assert summary.start is None
    assert summary.end is None


def test_finding_summary_forbids_extra_fields():
    with pytest.raises(ValidationError):
        PIIFindingSummary(
            category=PIICategory.PERSON_NAME,
            masked_value="Ш***** Д***** С*********",
            confidence=0.97,
            source=PIISource.PATTERN,
            detector="pattern.person_name",
            unexpected=True,
        )  # type: ignore[call-arg]


def _minimal_scan_result() -> PIIScanResult:
    return PIIScanResult(
        decision=PIIDecision.ALLOW,
        risk_level=PIIRiskLevel.MEDIUM,
        stage=PIIScanStage.DOCUMENT,
        destination=PIIDestination.INTERNAL_LLM,
        findings=[_minimal_summary()],
        findings_count=1,
        detector_version="1.0.0",
        policy_version="1.0.0",
        processed_at=datetime(2026, 9, 26, 10, 0, tzinfo=UTC),
    )


def test_scan_result_defaults():
    result = _minimal_scan_result()
    assert result.category_counts == {}
    assert result.reasons == []
    assert result.warnings == []


def test_scan_result_forbids_extra_fields():
    with pytest.raises(ValidationError):
        PIIScanResult(
            decision=PIIDecision.ALLOW,
            risk_level=PIIRiskLevel.MEDIUM,
            stage=PIIScanStage.DOCUMENT,
            destination=PIIDestination.INTERNAL_LLM,
            findings=[],
            findings_count=0,
            detector_version="1.0.0",
            policy_version="1.0.0",
            processed_at=datetime(2026, 9, 26, 10, 0, tzinfo=UTC),
            unexpected=True,
        )  # type: ignore[call-arg]


def _audit_record() -> PIIAuditRecord:
    return PIIAuditRecord(
        event="pii.scan.completed",
        document_id="2b8fdd0d",
        stage=PIIScanStage.DOCUMENT,
        decision=PIIDecision.ALLOW,
        risk_level=PIIRiskLevel.MEDIUM,
        findings_count=7,
        detector_version="1.0.0",
        policy_version="1.0.0",
        occurred_at=datetime(2026, 9, 26, 10, 0, tzinfo=UTC),
    )


def test_audit_record_shape():
    record = _audit_record()
    assert record.event == "pii.scan.completed"
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


def test_audit_record_forbids_extra_fields():
    with pytest.raises(ValidationError):
        PIIAuditRecord(
            event="pii.blocked",
            document_id="2b8fdd0d",
            stage=PIIScanStage.DOCUMENT,
            decision=PIIDecision.BLOCK,
            risk_level=PIIRiskLevel.CRITICAL,
            findings_count=1,
            detector_version="1.0.0",
            policy_version="1.0.0",
            occurred_at=datetime(2026, 9, 26, 10, 0, tzinfo=UTC),
            value="leaked",
        )  # type: ignore[call-arg]


def test_decision_result_defaults():
    decision = PIIDecisionResult(
        decision=PIIDecision.ALLOW_WITH_WARNING,
        risk_level=PIIRiskLevel.HIGH,
    )
    assert decision.actions == {}
    assert decision.reasons == []
    assert decision.warnings == []
    assert (
        PIIDecisionResult(
            decision=PIIDecision.REVIEW,
            risk_level=PIIRiskLevel.HIGH,
            actions={PIICategory.PASSPORT: PIIAction.REVIEW},
        ).actions[PIICategory.PASSPORT]
        is PIIAction.REVIEW
    )


def test_decision_result_forbids_extra_fields():
    with pytest.raises(ValidationError):
        PIIDecisionResult(
            decision=PIIDecision.ALLOW,
            risk_level=PIIRiskLevel.LOW,
            unexpected=True,
        )  # type: ignore[call-arg]


# --- the three security assertions (plan §5) ---------------------------------


def test_value_is_excluded_from_every_finding_dump_path():
    finding = _minimal_finding()
    for dumped in (
        finding.model_dump(),
        finding.model_dump(mode="json"),
        finding.model_dump_json(),
    ):
        serialized = dumped if isinstance(dumped, str) else str(dumped)
        assert "Шадеркин" not in serialized
    assert "value" not in finding.model_dump()
    assert "value_fingerprint" not in finding.model_dump()
    assert finding.model_dump()["masked_value"] == "Ш***** Д***** С*********"


def test_boundary_types_have_no_value_field():
    for model in (PIIFindingSummary, PIIScanResult, PIIAuditRecord):
        assert "value" not in model.model_fields
        assert "value_fingerprint" not in model.model_fields
    assert "masked_value" in PIIFindingSummary.model_fields


def test_finding_summary_schema_is_the_wire_contract():
    """``PIIFinding`` is not serializable, so Phase 2 must export the summary.

    ``Field(exclude=True)`` drops the field from ``model_dump()`` but not from
    ``model_json_schema()``, so the in-process type *is* schema-visible. Pinned
    here so ``PII_FINDING_SCHEMA`` stays derived from ``PIIFindingSummary``,
    whose schema genuinely has no ``value`` property.
    """
    assert "value" in PIIFinding.model_json_schema()["properties"]
    assert "value" not in PIIFindingSummary.model_json_schema()["properties"]
    assert "value_fingerprint" not in PIIFindingSummary.model_json_schema()["properties"]


def test_finding_is_not_hashable():
    """Frozen, but ``metadata`` is a dict — dedup on the key tuple, not the model."""
    with pytest.raises(TypeError):
        hash(_minimal_finding())


def test_audit_record_has_no_value_or_fingerprint():
    fields = PIIAuditRecord.model_fields
    assert "value" not in fields
    assert "value_fingerprint" not in fields
    assert "masked_value" not in fields
    assert "findings" not in fields
    assert "detector" not in fields


# --- exception hierarchy ----------------------------------------------------


def test_exception_hierarchy():
    for exc in (
        InvalidPIIInputError,
        PIIDetectorError,
        PIIPolicyError,
        PIIRedactionError,
        PIIDecisionError,
    ):
        assert issubclass(exc, PIIError)
    assert issubclass(PIIError, Exception)


# --- architectural boundaries (plan §0, §5) ----------------------------------


def test_pii_package_imports_no_infrastructure():
    for path in pii_source_files():
        offenders = imports_forbidden_infrastructure(path)
        assert not offenders, f"{path.name} must not import infrastructure: {offenders}"


def test_pii_package_imports_no_classification_or_canonical():
    """Runtime imports only — the one type-only borrow is allowed (Phase 3).

    Phase 1's guard was a substring scan and could not tell a runtime import
    from a ``if TYPE_CHECKING:`` one. Phase 3 introduces the sanctioned borrow
    (``NormalizedDocument``), so the scan became an AST walk that classifies
    imports: runtime imports must be clean, type-only imports are checked
    separately by ``test_pii_package_type_only_imports_are_narrow``.
    """
    for path in pii_source_files():
        offenders = imports_forbidden_domains(path)
        assert not offenders, f"{path.name} must not import domain types at runtime: {offenders}"


def test_pii_package_type_only_imports_are_narrow():
    """The complete set of type-only borrows is ``NormalizedDocument``, nothing else."""
    for path in pii_source_files():
        offenders = unexpected_type_only_imports(path)
        assert not offenders, f"{path.name} borrows unexpected type-only imports: {offenders}"


def test_pii_public_surface_is_sorted():
    assert app.pii.__all__ == sorted(app.pii.__all__)
