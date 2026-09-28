"""Sources of metadata that is always built by Python, never by the LLM."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExtractionMeta(BaseModel):
    """LLM extraction provenance: model, prompt, schema and token usage/cost."""

    model: str
    prompt_version: str
    schema_name: str = Field(serialization_alias="schema", validation_alias="schema")
    schema_version: str = "1.0.0"
    tokens: dict[str, int] = Field(default_factory=dict)
    cost_usd: float = 0.0


class ProcessingMeta(BaseModel):
    """Processing provenance: pipeline version plus extraction metadata."""

    pipeline_version: str = "1.0.0"
    extraction: ExtractionMeta | None = None


class SourceMeta(BaseModel):
    """Source document provenance (from the upload event, never the LLM)."""

    type: str = "user_upload"
    mime_type: str | None = None
    filename: str | None = None
    sha256: str | None = None
    object_key: str | None = None


class DocumentMeta(BaseModel):
    """Document-level administrative metadata."""

    language: str = "ru"
    document_date: str | None = None
    uploaded_at: datetime | None = None
    page_count: int | None = None


class ValidationMeta(BaseModel):
    """Validation result of the canonical payload against its schema."""

    status: str = "valid"
    schema_valid: bool = True
    warnings: list[str] = Field(default_factory=list)
    validated_at: datetime | None = None


class ClassificationMeta(BaseModel):
    """Classification 2.0 verdict recorded alongside a canonical document.

    A Python-determined (rule-based) classification outcome; the block appears
    in the YAML frontmatter and the ``analysis-completed`` event ``data``. The
    verbatim ``ClassificationResult`` lives in the versioned
    ``classification_result.json`` artifact.
    """

    model_config = ConfigDict(extra="forbid")

    document_type: str
    document_subtype: str | None = None
    confidence: float
    confidence_level: str
    decision: str
    method: str = "rule_score"
    classifier_version: str
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PIIMeta(BaseModel):
    """PII-gate verdict recorded alongside a canonical document.

    The Python-determined outcome of the PII gate; the block appears in the YAML
    frontmatter and the ``analysis-completed`` event ``data``, mirroring
    :class:`ClassificationMeta` exactly. The verbatim ``PIIScanResult`` lives in
    the versioned ``pii_result.json`` artifact — the only surface masked findings
    are persisted to in full.

    Every enum-valued field is a plain ``str``, not an enum, for the same reason
    ``ClassificationMeta``'s are: the taxonomy lives in ``app/pii`` and
    ``packages.canonical`` must not depend on the worker app (``PII GATE``
    plan §0, ORDER §8). The gate serialises the members; this model only records
    what it was told.

    ``category_counts`` is authoritative and ``categories`` is the convenience
    list derived from it for UI and metrics. Both are required, so a consumer
    that renders the list never has to recompute the tally and get the duplicate
    findings aggregation removes wrong.
    """

    model_config = ConfigDict(extra="forbid")

    decision: str
    risk_level: str
    stage: str
    destination: str
    findings_count: int
    category_counts: dict[str, int]
    categories: list[str]
    detector_version: str
    policy_version: str
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FrontmatterMeta(BaseModel):
    """Full YAML-frontmatter metadata envelope rendered around a document.

    ``doc_id``, ``type`` and ``subtype`` are read from the extraction envelope so
    all metadata lives in one place; everything else is Python-built.
    """

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    doc_id: str
    type: str
    subtype: str = ""
    document: DocumentMeta = Field(default_factory=DocumentMeta)
    source: SourceMeta = Field(default_factory=SourceMeta)
    processing: ProcessingMeta = Field(default_factory=ProcessingMeta)
    validation: ValidationMeta = Field(default_factory=ValidationMeta)
    classification: ClassificationMeta | None = None
    pii: PIIMeta | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True, by_alias=True)
