"""Contract-level tests for Classification 2.0 scoring/resolver (Phase 6)."""

from typing import Protocol

from app.classification import CLASSIFIER_VERSION
from app.classification.models import DocumentType
from app.classification.resolver import (
    SCHEMA_PROMPT_KEY,
    SCHEMA_REGISTRY,
    RegistrySchemaResolver,
    SchemaResolver,
)
from app.classification.scoring import (
    THRESH_HIGH_MIN,
    THRESH_MED_LOW,
    WEIGHT_CONTRADICTING,
    WEIGHT_MEDIUM,
    WEIGHT_STRONG,
    WEIGHT_WEAK,
    ScoringEngine,
)


def test_classifier_version_constant():
    assert CLASSIFIER_VERSION == "2.0.0"


def test_contract_weight_constants():
    assert WEIGHT_STRONG == 5.0
    assert WEIGHT_MEDIUM == 3.0
    assert WEIGHT_WEAK == 1.0
    assert WEIGHT_CONTRADICTING == -4.0


def test_threshold_constants():
    assert THRESH_HIGH_MIN == 0.90
    assert THRESH_MED_LOW == 0.70


def test_scoring_engine_is_protocol():
    assert issubclass(ScoringEngine, Protocol)


class _ScoringStub(ScoringEngine):
    """Structurally conforming stub for contract proof."""

    def score(self, signals):
        return (
            DocumentType.LABORATORY,
            1.0,
            ["laboratory_section_detected"],
            "accept",
            "high",
        )


def test_scoring_protocol_is_usable():
    engine: ScoringEngine = _ScoringStub()
    result = engine.score([])
    assert result[0] == DocumentType.LABORATORY


def test_schema_registry_locked_shape():
    assert SCHEMA_REGISTRY[("laboratory", "hematology")] == "laboratory.v1"
    assert SCHEMA_REGISTRY[("laboratory", None)] == "laboratory.v1"
    assert SCHEMA_REGISTRY[("appointment", None)] == "appointment.v1"
    assert SCHEMA_REGISTRY[("prescription", None)] == "prescription.v1"
    assert SCHEMA_REGISTRY[("other", None)] == "generic.v1"
    for t in ("discharge", "diagnosis", "imaging", "consultation"):
        assert SCHEMA_REGISTRY[(t, None)] == "generic.v1"


def test_schema_resolver_is_protocol():
    assert issubclass(SchemaResolver, Protocol)


def test_schema_prompt_key_mapping():
    assert SCHEMA_PROMPT_KEY["laboratory.v1"] == "laboratory"
    assert SCHEMA_PROMPT_KEY["prescription.v1"] == "prescription"
    assert SCHEMA_PROMPT_KEY["generic.v1"] == "default"
    assert SCHEMA_PROMPT_KEY["appointment.v1"] == "default"


def test_registry_resolver_maps_classification_to_prompt_key():
    resolver = RegistrySchemaResolver()
    assert resolver.resolve(DocumentType.LABORATORY) == "laboratory"
    assert resolver.resolve(DocumentType.LABORATORY, "hematology") == "laboratory"
    assert resolver.resolve(DocumentType.PRESCRIPTION) == "prescription"
    assert resolver.resolve(DocumentType.OTHER) == "default"


def test_registry_resolver_appointment_falls_back_to_default_prompt():
    resolver = RegistrySchemaResolver()
    assert resolver.resolve(DocumentType.APPOINTMENT) == "default"


def test_registry_resolver_unknown_type_falls_back_to_default_prompt():
    resolver = RegistrySchemaResolver()
    assert resolver.resolve("doctor_report") == "default"
    assert resolver.resolve(DocumentType.DISCHARGE) == "default"


def test_full_public_api_smoke():
    from app.classification import (
        ClassificationConfidenceLevel,
        ClassificationDecision,
        ClassificationResult,
        DocumentType,
        NormalizedDocument,
    )

    assert CLASSIFIER_VERSION == "2.0.0"
    assert DocumentType.LABORATORY == "laboratory"
    assert ClassificationDecision.ACCEPT == "accept"
    assert ClassificationConfidenceLevel.HIGH == "high"
    assert ClassificationResult is not None
    assert NormalizedDocument is not None