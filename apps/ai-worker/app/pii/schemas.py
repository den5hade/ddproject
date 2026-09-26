"""Stable JSON Schema wire contracts for the PII gate (M4 Phase 2).

Schema dicts are derived at import time from the Phase 1 Pydantic models, so
enum values, required fields and defaults cannot drift from the contract types —
the same approach as ``app/classification/schemas.py:19-23``. No schema
generation CLI is provided; the dicts are importable constants forming the
frozen wire shape. Consequently the ``description`` entries below are the Phase 1
model docstrings: the schema is documentation and contract in one artifact, and
is never hand-maintained.

What these schemas are **not**:

- Not a source of truth. ``app/pii/models.py`` is; regenerate by re-importing.
- Not derived from ``PIIFinding``. That type is in-process only and its
  ``value``/``value_fingerprint`` fields are ``Field(exclude=True)`` — excluded
  from serialization but *not* from ``model_json_schema()``, so deriving a wire
  contract from it would produce a schema that both declares and cannot carry
  the field it most needs to hide. ``PII_FINDING_SCHEMA`` therefore comes from
  ``PIIFindingSummary``, whose shape has no value field at all. This is the
  machine-checkable form of the "no raw PII crosses a boundary" invariant
  (plan §5): a validator or consumer reading this schema cannot request a raw
  value, because the property does not exist.

Enum values and constraints:
- ``category`` (``PIICategory``): one of the 23 members in ``PIICategory``
  (ref: plan §4.1). Reused across the scan result and each finding.
- ``decision``: one of ``allow|allow_with_warning|review|block``.
- ``risk_level``: one of ``low|medium|high|critical``.
- ``destination``: one of ``internal_llm|external_llm|persistence|unknown``.
- ``stage``: one of ``document|canonical``.
- ``source``: one of ``pattern|structured_field|ner|llm|canonical``; the
  ``canonical`` member is what makes a post-extraction guard finding
  distinguishable from a source-document scan in the persisted result.
- ``confidence``: documented range 0.0 <= confidence <= 1.0 (not enforced).
- ``findings_count``: must equal ``len(findings)`` (documented, not enforced).
- ``category_counts``: map of category value to occurrence count; the
  authoritative per-category tally (``categories`` in the frontmatter block is a
  convenience list derived from it).
- ``processed_at`` / ``occurred_at``: RFC 3339 date-time, timezone-aware.
"""

from app.pii.models import PIIFindingSummary, PIIScanResult

PII_SCAN_RESULT_SCHEMA: dict = PIIScanResult.model_json_schema()
"""JSON Schema document for the locked ``PIIScanResult`` wire shape.

The shape persisted as ``pii_result.json`` and mirrored (as the ``pii``
frontmatter block) into the canonical payload. Carries no values and no
fingerprints; the nested ``findings[]`` items are ``PIIFindingSummary``.
"""

PII_FINDING_SCHEMA: dict = PIIFindingSummary.model_json_schema()
"""JSON Schema document for a single ``findings[]`` item.

The only finding shape allowed on the wire: ``masked_value`` and nothing else
sensitive. Derived from ``PIIFindingSummary``, never from ``PIIFinding``.
"""

__all__ = ["PII_FINDING_SCHEMA", "PII_SCAN_RESULT_SCHEMA"]
