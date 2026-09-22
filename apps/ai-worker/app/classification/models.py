"""Classification 2.0 domain contract types.

Contract-only enums and Pydantic models for the deterministic rule-based
classification pipeline. No scoring or detection logic lives here; field
shapes and enum values are the locked wire contract (classifier_version
policy: see CONTRACT_IMPL_PLAN.md §7).
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentType(str, Enum):
    """Canonical document type assigned by classification."""

    LABORATORY = "laboratory"
    APPOINTMENT = "appointment"
    PRESCRIPTION = "prescription"
    DISCHARGE = "discharge"
    DIAGNOSIS = "diagnosis"
    IMAGING = "imaging"
    CONSULTATION = "consultation"
    OTHER = "other"


class LaboratorySubtype(str, Enum):
    """Subtype refinement for ``DocumentType.LABORATORY`` documents."""

    HEMATOLOGY = "hematology"
    BIOCHEMISTRY = "biochemistry"
    URINALYSIS = "urinalysis"
    HORMONES = "hormones"
    MICROBIOLOGY = "microbiology"
    UNKNOWN = "unknown"


class ClassificationConfidenceLevel(str, Enum):
    """Banded confidence level derived from the numeric confidence score."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ClassificationDecision(str, Enum):
    """Final decision produced by the classification contract."""

    ACCEPT = "accept"
    AMBIGUOUS = "ambiguous"
    FALLBACK = "fallback"


class ClassificationMethod(str, Enum):
    """How the classification decision was produced.

    ``ClassificationResult.method`` is typed as the equivalent string
    ``Literal`` to match the locked contract shape; this enum exists for
    programmatic comparison.
    """

    RULE_SCORE = "rule_score"
    LLM_FALLBACK = "llm_fallback"
    MANUAL = "manual"


class ClassificationSignal(BaseModel):
    """A single inspectable signal considered during scoring.

    Field contract only — signals are produced by detector stubs (Phase 5)
    and scored by the scoring engine (Phase 6); no logic here.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    weight: float
    matched: bool
    matches: int = 0
    score: float = 0.0


class ClassificationResult(BaseModel):
    """Locked classification output contract (wire shape).

    ``confidence`` is documented to the range 0.0–1.0; range enforcement is
    documentation-only in M1 (no validator). ``classifier_version`` carries
    the contract version string (baseline ``"2.0.0"``, Phase 6).
    """

    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType
    document_subtype: str | None = None
    confidence: float
    confidence_level: ClassificationConfidenceLevel
    decision: ClassificationDecision
    method: Literal["rule_score", "llm_fallback", "manual"] = "rule_score"
    reasons: list[str]
    signals: list[ClassificationSignal]
    classifier_version: str
    warnings: list[str] = Field(default_factory=list)
