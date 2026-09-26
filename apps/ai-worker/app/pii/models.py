"""PII gate domain contract types.

Contract-only enums and Pydantic models for the PII gate (milestone M4,
``PII GATE/IMPL_PLAN.md`` Phase 1). No detection, masking, redaction, policy or
gate logic lives here — field shapes and enum values are the locked wire
contract. Risk and action are *policy configuration*, never detection output
(``PII GATE/IMPL_ARCH.md`` §12, §17), so nothing on these models carries a verdict.

Three invariants are enforced structurally by the field definitions below, not
by convention at call sites:

1. No raw PII value crosses a boundary. ``PIIFinding.value`` is
   ``Field(exclude=True)``, so it is structurally absent from every
   ``model_dump()`` path; ``PIIFindingSummary``, ``PIIScanResult`` and
   ``PIIAuditRecord`` have no value field at all.
2. ``value_fingerprint`` is a salted HMAC-SHA256 produced by
   ``masking.hash_pii_value`` (Phase 4) — never a plain digest, never logged,
   never persisted in the frontmatter/event block. It lives on the
   in-process ``PIIFinding`` only.
3. The gate is a document-level capability. This module imports no
   ``app.classification`` and no ``packages.canonical`` type; when the pipeline
   needs a document type inside policy it passes a plain ``str``.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "PIIAction",
    "PIICategory",
    "PIIDecision",
    "PIIDecisionResult",
    "PIIDestination",
    "PIIFinding",
    "PIIFindingSummary",
    "PIIRiskLevel",
    "PIIScanResult",
    "PIIScanStage",
    "PIISource",
]


class PIICategory(str, Enum):
    """Sensitive-entity taxonomy (``PII GATE/IMPL_ARCH.md`` §3, §4; plan §4.1).

    Members are declared group by group; the order is the declaration order and
    is what ``PIICategory.model_json_schema()`` emits. A new member is a
    **minor** contract event and *must* come with a row in
    ``policy.DEFAULT_POLICY`` (Phase 5) and a rule in the mask table
    (Phase 4) — otherwise it inherits no action and no mask.
    """

    # identity
    PERSON_NAME = "person_name"
    DATE_OF_BIRTH = "date_of_birth"
    AGE = "age"
    GENDER = "gender"
    NATIONALITY = "nationality"
    # contact
    EMAIL = "email"
    PHONE = "phone"
    ADDRESS = "address"
    # government / legal identifiers
    PASSPORT = "passport"
    NATIONAL_ID = "national_id"
    INSURANCE_NUMBER = "insurance_number"
    SNILS = "snils"
    INN = "inn"
    # medical identifiers
    PATIENT_ID = "patient_id"
    MEDICAL_RECORD_NUMBER = "medical_record_number"
    LAB_ORDER_ID = "lab_order_id"
    ENCOUNTER_ID = "encounter_id"
    TICKET_NUMBER = "ticket_number"
    # practitioner / organization (not patient PII — plan §4.1)
    DOCTOR_NAME = "doctor_name"
    DOCTOR_LICENSE = "doctor_license"
    ORGANIZATION_NAME = "organization_name"
    ORGANIZATION_ID = "organization_id"
    # secrets (the only ``BLOCK`` category in the default policy)
    SECRET = "secret"


class PIISource(str, Enum):
    """Mechanism that produced a finding (``PII GATE/IMPL_ARCH.md`` §7–§11).

    ``CANONICAL`` marks a finding raised by the post-extraction guard
    (``canonical_guard.py``, Phase 6) rather than by a source-document scan, so
    the two boundaries stay attributable in the persisted result.
    """

    PATTERN = "pattern"
    STRUCTURED_FIELD = "structured_field"
    NER = "ner"
    LLM = "llm"
    CANONICAL = "canonical"


class PIIRiskLevel(str, Enum):
    """Risk ladder assigned by policy, not by detection (IMPL_ARCH §12)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PIIAction(str, Enum):
    """Per-category action assigned by the policy engine (IMPL_ARCH §17)."""

    ALLOW = "allow"
    WARN = "warn"
    REDACT = "redact"
    REVIEW = "review"
    BLOCK = "block"


class PIIDecision(str, Enum):
    """Final gate decision (IMPL_ARCH §13).

    ``PIIDecision`` follows IMPL_ARCH's enum vocabulary, not the
    ``{"status": "allowed"}`` sketch in ``ORDER.md`` §2 — the IMPL_ARCH enum wins and
    the deviation is recorded in the plan (§7).

    PII presence alone never blocks: a medical document is *expected* to carry
    patient identity. ``BLOCK`` is reserved for ``PIICategory.SECRET`` and
    fail-closed conditions; ``REVIEW`` for unexpected high-risk combinations.
    """

    ALLOW = "allow"
    ALLOW_WITH_WARNING = "allow_with_warning"
    REVIEW = "review"
    BLOCK = "block"


class PIIDestination(str, Enum):
    """Where the scanned text is about to be sent (IMPL_ARCH §16, §17).

    The current provider is external but trusted by name
    (``ai_base_url = https://foundation-models.api.cloud.ru/v1``), so
    ``INTERNAL_LLM`` is the locked default: no pre-extraction redaction runs
    today. ``UNKNOWN`` fails closed (``REVIEW``) — it is not a synonym for
    ``INTERNAL_LLM``. Policy is data, so switching to ``EXTERNAL_LLM`` is a
    configuration change, not a code change.
    """

    INTERNAL_LLM = "internal_llm"
    EXTERNAL_LLM = "external_llm"
    PERSISTENCE = "persistence"
    UNKNOWN = "unknown"


class PIIScanStage(str, Enum):
    """Which boundary produced a result."""

    DOCUMENT = "document"
    CANONICAL = "canonical"


class PIIFinding(BaseModel):
    """One detected sensitive entity — **in-process only**.

    Frozen and ``extra="forbid"``. This is the only type carrying raw text, and
    it is not serializable: ``value`` and ``value_fingerprint`` are excluded
    from every ``model_dump()`` path, so logs, audit records, events, artifacts
    and frontmatter cannot receive them even by accident. Crossing a boundary
    happens through :class:`PIIFindingSummary`, which has no field for either.

    ``value`` is required (not ``str | None`` as in IMPL_ARCH §5) so a finding cannot
    exist without the text that justified it — redaction (Phase 4) needs the
    real substring in-process, and the alternative makes "no raw value" a
    call-site discipline instead of a control.

    ``confidence`` is documented to the range 0.0–1.0; range enforcement is
    documentation-only, mirroring ``ClassificationResult.confidence``.
    ``value_fingerprint`` is a salted HMAC-SHA256 (plan §0) and is never logged.

    Two traps for later phases:

    - ``model_json_schema()`` on this type still lists ``value`` and
      ``value_fingerprint`` — ``exclude`` is a serialization concern, not a
      schema one — so ``PIIFinding`` is **not** a wire contract. Phase 2
      exports ``PIIFindingSummary`` for that reason; never derive a schema or
      an artifact from ``PIIFinding``.
    - ``metadata`` is a ``dict``, so the frozen model is not hashable in
      practice. The Phase 3 aggregator must dedup on the
      ``(category, value_fingerprint)`` tuple, not on the model.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: PIICategory
    value: str = Field(exclude=True)
    masked_value: str
    value_fingerprint: str = Field(exclude=True)
    confidence: float
    source: PIISource
    detector: str
    detector_version: str
    start: int | None = None
    end: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PIIFindingSummary(BaseModel):
    """A finding reduced to what may cross a boundary.

    ``masked_value`` only: no ``value``, no ``value_fingerprint`` (IMPL_ARCH §6, §19).
    This is the shape persisted in ``pii_result.json`` and mirrored in the
    frontmatter ``pii`` block. ``start``/``end`` are optional because a
    structured-field or canonical-guard finding may have no text offsets.
    """

    model_config = ConfigDict(extra="forbid")

    category: PIICategory
    masked_value: str
    confidence: float
    source: PIISource
    detector: str
    start: int | None = None
    end: int | None = None


class PIIScanResult(BaseModel):
    """Aggregate gate output — the persisted, boundary-safe projection.

    Distinct from :class:`PIIDecisionResult`, the policy engine's internal
    output: this type is what gets serialized, so it carries no action map and
    no detector internals. ``findings_count`` must equal ``len(findings)``
    (documentation-only invariant, same convention as ``confidence``).
    ``processed_at`` is expected to be timezone-aware.
    """

    model_config = ConfigDict(extra="forbid")

    decision: PIIDecision
    risk_level: PIIRiskLevel
    stage: PIIScanStage
    destination: PIIDestination
    findings: list[PIIFindingSummary]
    findings_count: int
    detector_version: str
    policy_version: str
    processed_at: datetime
    category_counts: dict[str, int] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PIIAuditRecord(BaseModel):
    """Audit projection of a gate decision (IMPL_ARCH §22).

    Written for every scan, blocked, review and redaction event. Carries no
    values, no fingerprints and no detector internals — the record proves *that
    a decision was taken*, never *what was found*. Known ``event`` values:
    ``pii.scan.completed``, ``pii.blocked``, ``pii.review.required``,
    ``pii.redacted``.
    """

    model_config = ConfigDict(extra="forbid")

    event: str
    document_id: str
    stage: PIIScanStage
    decision: PIIDecision
    risk_level: PIIRiskLevel
    findings_count: int
    detector_version: str
    policy_version: str
    occurred_at: datetime


class PIIDecisionResult(BaseModel):
    """Policy engine output — internal, never persisted as-is.

    Carries the per-category action map that :class:`PIIScanResult` drops, so
    M5 can act on a ``REDACT`` without re-deriving it from the decision. The
    gate projects this into a :class:`PIIScanResult` before anything crosses a
    boundary. ``decision`` is the highest-precedence action across
    ``findings``: ``BLOCK > REVIEW > ALLOW_WITH_WARNING > ALLOW``.
    """

    model_config = ConfigDict(extra="forbid")

    decision: PIIDecision
    risk_level: PIIRiskLevel
    actions: dict[PIICategory, PIIAction] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
