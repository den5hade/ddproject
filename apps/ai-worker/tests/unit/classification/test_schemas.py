"""Contract-level tests for Classification 2.0 schema exports (Phase 2)."""

from app.classification.models import ClassificationResult, ClassificationSignal
from app.classification.schemas import (
    CLASSIFICATION_RESULT_SCHEMA,
    CLASSIFICATION_SIGNAL_SCHEMA,
)


def test_result_schema_locked_keys():
    required = CLASSIFICATION_RESULT_SCHEMA["required"]
    for key in (
        "document_type",
        "confidence",
        "confidence_level",
        "decision",
        "reasons",
        "signals",
        "classifier_version",
    ):
        assert key in required
    assert "warnings" in CLASSIFICATION_RESULT_SCHEMA["properties"]
    assert "method" in CLASSIFICATION_RESULT_SCHEMA["properties"]


def test_result_schema_forbids_extra_properties():
    assert CLASSIFICATION_RESULT_SCHEMA["additionalProperties"] is False


def test_result_schema_enum_values_match_models():
    props = CLASSIFICATION_RESULT_SCHEMA["properties"]
    assert props["document_type"]["$ref"] == "#/$defs/DocumentType"

    defs = CLASSIFICATION_RESULT_SCHEMA["$defs"]
    doc_type = ClassificationResult.model_fields["document_type"].annotation
    assert defs["DocumentType"]["enum"] == [m.value for m in doc_type]
    assert defs["ClassificationDecision"]["enum"] == [
        "accept",
        "ambiguous",
        "fallback",
    ]
    assert defs["ClassificationConfidenceLevel"]["enum"] == ["high", "medium", "low"]
    assert props["method"]["enum"] == ["rule_score", "llm_fallback", "manual"]


def test_signal_schema_matches_model():
    ref = CLASSIFICATION_SIGNAL_SCHEMA
    assert ref["required"] == ["name", "weight", "matched"]
    assert ref["additionalProperties"] is False
    assert ref["properties"]["matches"]["default"] == 0
    assert ref["properties"]["score"]["default"] == 0.0
    assert ref == ClassificationSignal.model_json_schema()