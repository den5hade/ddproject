"""Contract-level tests for PII gate schema exports (M4 Phase 2).

Locks the serialized wire shape: required keys, ``additionalProperties: false``,
enum parity with the Phase 1 models, and — the assertion that carries the
security value — that no ``value``/``value_fingerprint`` property exists
anywhere in either schema document.
"""

import json
from datetime import UTC, datetime
from typing import Any

from app.pii.models import (
    PIICategory,
    PIIDecision,
    PIIDestination,
    PIIFindingSummary,
    PIIRiskLevel,
    PIIScanResult,
    PIIScanStage,
    PIISource,
)
from app.pii.schemas import PII_FINDING_SCHEMA, PII_SCAN_RESULT_SCHEMA

_FORBIDDEN_PROPERTIES = ("value", "value_fingerprint")


def _property_names(node: Any) -> list[str]:
    """Every ``properties`` key anywhere in a schema document, at any depth."""
    names: list[str] = []
    if isinstance(node, dict):
        names.extend(node.get("properties", {}).keys())
        for value in node.values():
            names.extend(_property_names(value))
    elif isinstance(node, list):
        for item in node:
            names.extend(_property_names(item))
    return names


def test_scan_result_schema_locked_keys():
    required = PII_SCAN_RESULT_SCHEMA["required"]
    for key in (
        "decision",
        "risk_level",
        "stage",
        "destination",
        "findings",
        "findings_count",
        "detector_version",
        "policy_version",
        "processed_at",
    ):
        assert key in required
    for optional in ("category_counts", "reasons", "warnings"):
        assert optional in PII_SCAN_RESULT_SCHEMA["properties"]
        assert optional not in required


def test_scan_result_schema_forbids_extra_properties():
    assert PII_SCAN_RESULT_SCHEMA["additionalProperties"] is False
    assert PII_SCAN_RESULT_SCHEMA["type"] == "object"
    assert PII_SCAN_RESULT_SCHEMA["title"] == "PIIScanResult"


def test_scan_result_schema_field_types():
    props = PII_SCAN_RESULT_SCHEMA["properties"]
    assert props["findings"]["type"] == "array"
    assert props["findings"]["items"] == {"$ref": "#/$defs/PIIFindingSummary"}
    assert props["findings_count"]["type"] == "integer"
    assert props["detector_version"]["type"] == "string"
    assert props["policy_version"]["type"] == "string"
    assert props["processed_at"]["format"] == "date-time"
    assert props["category_counts"]["type"] == "object"
    assert props["category_counts"]["additionalProperties"] == {"type": "integer"}
    assert props["reasons"]["items"] == {"type": "string"}


def test_scan_result_schema_references_locked_defs():
    props = PII_SCAN_RESULT_SCHEMA["properties"]
    defs = PII_SCAN_RESULT_SCHEMA["$defs"]
    assert props["decision"]["$ref"] == "#/$defs/PIIDecision"
    assert props["risk_level"]["$ref"] == "#/$defs/PIIRiskLevel"
    assert props["stage"]["$ref"] == "#/$defs/PIIScanStage"
    assert props["destination"]["$ref"] == "#/$defs/PIIDestination"
    assert defs["PIIFindingSummary"]["additionalProperties"] is False


def test_scan_result_schema_enum_parity_with_models():
    defs = PII_SCAN_RESULT_SCHEMA["$defs"]
    assert defs["PIICategory"]["enum"] == [m.value for m in PIICategory]
    assert defs["PIISource"]["enum"] == [m.value for m in PIISource]
    assert defs["PIIDecision"]["enum"] == [m.value for m in PIIDecision]
    assert defs["PIIRiskLevel"]["enum"] == [m.value for m in PIIRiskLevel]
    assert defs["PIIDestination"]["enum"] == [m.value for m in PIIDestination]
    assert defs["PIIScanStage"]["enum"] == [m.value for m in PIIScanStage]
    # A post-extraction guard finding must be representable on the wire.
    assert "canonical" in defs["PIISource"]["enum"]


def test_finding_schema_locked_keys():
    assert set(PII_FINDING_SCHEMA["required"]) == {
        "category",
        "masked_value",
        "confidence",
        "source",
        "detector",
    }
    assert set(PII_FINDING_SCHEMA["properties"]) == {
        "category",
        "masked_value",
        "confidence",
        "source",
        "detector",
        "start",
        "end",
    }
    assert PII_FINDING_SCHEMA["additionalProperties"] is False


def test_finding_schema_has_no_value_property():
    """The machine-checkable "no raw PII" invariant (plan §5, assertion 2)."""
    properties = PII_FINDING_SCHEMA["properties"]
    for forbidden in _FORBIDDEN_PROPERTIES:
        assert forbidden not in properties
    assert "masked_value" in properties
    assert properties["confidence"]["type"] == "number"


def test_no_value_property_anywhere_in_either_schema():
    """Deep check: a value field must not hide in a nested ``$defs`` entry."""
    for schema in (PII_FINDING_SCHEMA, PII_SCAN_RESULT_SCHEMA):
        names = _property_names(schema)
        for forbidden in _FORBIDDEN_PROPERTIES:
            assert forbidden not in names, f"{forbidden} present in {schema.get('title')}"


def test_schemas_match_models_exactly():
    assert PIIFindingSummary.model_json_schema() == PII_FINDING_SCHEMA
    assert PIIScanResult.model_json_schema() == PII_SCAN_RESULT_SCHEMA


def test_schemas_are_independent_objects():
    """Two ``model_json_schema()`` calls must not share mutable sub-dicts."""
    nested = PII_SCAN_RESULT_SCHEMA["$defs"]["PIIFindingSummary"]
    assert nested is not PII_FINDING_SCHEMA
    assert nested["required"] == PII_FINDING_SCHEMA["required"]


def test_schemas_are_json_serializable():
    """M5 writes these shapes to ``pii_result.json``; they must round-trip."""
    for schema in (PII_FINDING_SCHEMA, PII_SCAN_RESULT_SCHEMA):
        assert json.loads(json.dumps(schema, ensure_ascii=False)) == schema


def test_schemas_never_derived_from_pii_finding():
    """``PIIFinding`` is in-process only — its schema would declare the value."""
    from app.pii import PIIFinding

    finding_schema = PIIFinding.model_json_schema()
    assert "value" in finding_schema["properties"]
    assert "value" in finding_schema["required"]
    assert finding_schema != PII_FINDING_SCHEMA


def test_real_payload_conforms_to_schema():
    """A real ``PIIScanResult`` serializes exactly to the locked shape.

    Walks the emitted payload (what M5 writes to ``pii_result.json``) against the
    schema properties. Deliberately dependency-free: M4 budgets no new
    dependency, and required/allowed keys plus enum membership are exactly what
    can drift between the model and its schema.
    """
    scan_result = PIIScanResult(
        decision=PIIDecision.ALLOW,
        risk_level=PIIRiskLevel.MEDIUM,
        stage=PIIScanStage.DOCUMENT,
        destination=PIIDestination.INTERNAL_LLM,
        findings=[
            PIIFindingSummary(
                category=PIICategory.PERSON_NAME,
                masked_value="Ш***** Д***** С*********",
                confidence=0.97,
                source=PIISource.PATTERN,
                detector="pattern.person_name",
                start=12,
                end=36,
            ),
            PIIFindingSummary(
                category=PIICategory.SNILS,
                masked_value="***-***-*** **",
                confidence=0.99,
                source=PIISource.STRUCTURED_FIELD,
                detector="structured_field.labelled",
            ),
        ],
        findings_count=2,
        category_counts={"person_name": 1, "snils": 1},
        reasons=["expected_medical_identity"],
        detector_version="1.0.0",
        policy_version="1.0.0",
        processed_at=datetime(2026, 9, 26, 10, 0, tzinfo=UTC),
    )
    payload = scan_result.model_dump(mode="json")

    schema = PII_SCAN_RESULT_SCHEMA
    assert set(payload) == set(schema["properties"])
    assert set(schema["required"]) <= set(payload)

    for item, item_schema in zip(payload["findings"], [PII_FINDING_SCHEMA] * 2, strict=True):
        assert set(item) == set(item_schema["properties"])
        assert item["category"] in PIICategory.__members__.values()
        assert item["source"] in PIISource.__members__.values()
    assert payload["decision"] in PIIDecision.__members__.values()
    assert payload["risk_level"] in PIIRiskLevel.__members__.values()
    assert payload["stage"] in PIIScanStage.__members__.values()
    assert payload["destination"] in PIIDestination.__members__.values()

    # End-to-end: the payload M5 persists carries no raw value, at any depth.
    assert not [key for key in _property_names(payload) if key in _FORBIDDEN_PROPERTIES]
    assert "Шадеркин" not in json.dumps(payload, ensure_ascii=False)
