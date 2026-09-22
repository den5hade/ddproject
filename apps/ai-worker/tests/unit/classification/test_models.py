"""Contract-level tests for Classification 2.0 domain types (Phase 1)."""

import pytest
from app.classification import (
    ClassificationConfidenceLevel,
    ClassificationDecision,
    ClassificationError,
    ClassificationMethod,
    ClassificationResult,
    ClassificationSignal,
    DocumentType,
    InvalidClassificationInputError,
    LaboratorySubtype,
    SchemaResolutionError,
)
from pydantic import ValidationError


def test_document_type_values():
    assert DocumentType.LABORATORY == "laboratory"
    assert DocumentType.APPOINTMENT == "appointment"
    assert DocumentType.PRESCRIPTION == "prescription"
    assert DocumentType.DISCHARGE == "discharge"
    assert DocumentType.DIAGNOSIS == "diagnosis"
    assert DocumentType.IMAGING == "imaging"
    assert DocumentType.CONSULTATION == "consultation"
    assert DocumentType.OTHER == "other"
    assert len(DocumentType) == 8


def test_laboratory_subtype_values():
    assert LaboratorySubtype.HEMATOLOGY == "hematology"
    assert LaboratorySubtype.BIOCHEMISTRY == "biochemistry"
    assert LaboratorySubtype.URINALYSIS == "urinalysis"
    assert LaboratorySubtype.HORMONES == "hormones"
    assert LaboratorySubtype.MICROBIOLOGY == "microbiology"
    assert LaboratorySubtype.UNKNOWN == "unknown"
    assert len(LaboratorySubtype) == 6


def test_confidence_level_and_decision_values():
    assert ClassificationConfidenceLevel.HIGH == "high"
    assert ClassificationConfidenceLevel.MEDIUM == "medium"
    assert ClassificationConfidenceLevel.LOW == "low"
    assert ClassificationDecision.ACCEPT == "accept"
    assert ClassificationDecision.AMBIGUOUS == "ambiguous"
    assert ClassificationDecision.FALLBACK == "fallback"


def test_method_enum_values():
    assert ClassificationMethod.RULE_SCORE == "rule_score"
    assert ClassificationMethod.LLM_FALLBACK == "llm_fallback"
    assert ClassificationMethod.MANUAL == "manual"


def test_signal_defaults():
    signal = ClassificationSignal(name="laboratory_section", weight=5.0, matched=True)
    assert signal.matches == 0
    assert signal.score == 0.0


def test_signal_forbids_extra_fields():
    with pytest.raises(ValidationError):
        ClassificationSignal(name="x", weight=1.0, matched=False, unexpected=True)  # type: ignore[call-arg]


def _minimal_result() -> ClassificationResult:
    return ClassificationResult(
        document_type=DocumentType.LABORATORY,
        confidence=0.96,
        confidence_level=ClassificationConfidenceLevel.HIGH,
        decision=ClassificationDecision.ACCEPT,
        reasons=["laboratory_section_detected"],
        signals=[],
        classifier_version="2.0.0",
    )


def test_result_minimal_construction_and_defaults():
    result = _minimal_result()
    assert result.document_type == DocumentType.LABORATORY
    assert result.document_subtype is None
    assert result.method == "rule_score"
    assert result.warnings == []
    assert result.classifier_version == "2.0.0"


def test_result_forbids_extra_fields():
    with pytest.raises(ValidationError):
        ClassificationResult(
            document_type=DocumentType.OTHER,
            confidence=0.5,
            confidence_level=ClassificationConfidenceLevel.LOW,
            decision=ClassificationDecision.FALLBACK,
            reasons=[],
            signals=[],
            classifier_version="2.0.0",
            unexpected=True,
        )  # type: ignore[call-arg]


def test_exception_hierarchy():
    assert issubclass(InvalidClassificationInputError, ClassificationError)
    assert issubclass(SchemaResolutionError, ClassificationError)
    assert issubclass(ClassificationError, Exception)
