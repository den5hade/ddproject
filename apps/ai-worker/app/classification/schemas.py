"""Stable JSON Schema wire contracts for classification (Classification 2.0).

Schema dicts are derived from the Phase 1 Pydantic models so enum values,
required fields and defaults always stay in sync with the contract types.
No schema-generation CLI is provided in M1; the dicts are importable
constants forming the frozen wire shape.

Enum values and constraints:
- ``document_type``: one of ``laboratory|appointment|prescription|discharge|
  diagnosis|imaging|consultation|other`` (ref: ``DocumentType``).
- ``confidence_level``: one of ``high|medium|low``.
- ``decision``: one of ``accept|ambiguous|fallback``.
- ``method``: one of ``rule_score|llm_fallback|manual`` (default ``rule_score``).
- ``confidence``: documented range 0.0 <= confidence <= 1.0 (not enforced in M1).
"""

from app.classification.models import ClassificationResult, ClassificationSignal

CLASSIFICATION_RESULT_SCHEMA: dict = ClassificationResult.model_json_schema()
"""JSON Schema document for the locked ``ClassificationResult`` wire shape."""

CLASSIFICATION_SIGNAL_SCHEMA: dict = ClassificationSignal.model_json_schema()
"""JSON Schema document for a single ``signals[]`` item."""

__all__ = ["CLASSIFICATION_RESULT_SCHEMA", "CLASSIFICATION_SIGNAL_SCHEMA"]