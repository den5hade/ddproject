"""Canonical extraction schemas: the per-document-type source of truth.

The ``BaseCanonical`` envelope carries administrative fields plus a
doc-type-specific payload. Each concrete class (laboratory, prescription,
generic) defines ``fields`` as a validated Pydantic model.
"""

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "BaseCanonical",
    "CANONICAL_MODELS",
    "DEFAULT_CANONICAL_MODEL",
    "GenericCanonical",
    "LaboratoryCanonical",
    "PrescriptionCanonical",
    "build_canonical",
]


class Institution(BaseModel):
    """The issuing healthcare institution (never includes patient PII)."""

    name: str | None = None
    address: str | None = None
    ogrn: str | None = None


class ResultItem(BaseModel):
    """A single laboratory measurement."""

    name: str
    value: str | float | None = None
    unit: str | None = None
    reference_min: str | float | None = None
    reference_max: str | float | None = None
    flagged: bool = False
    interpretation: str | None = None
    comment: str | None = None


class ResultSet(BaseModel):
    """:class:`LaboratoryCanonical` payload: a list of measurements."""

    results: list[ResultItem] = Field(default_factory=list)


class Medication(BaseModel):
    """A single prescribed medication."""

    name: str
    dosage: str | None = None
    frequency: str | None = None
    duration: str | None = None


class PrescriptionPayload(BaseModel):
    """:class:`PrescriptionCanonical` payload: medications plus issuing context."""

    medications: list[Medication] = Field(default_factory=list)
    doctor: str | None = None
    issued_at: str | None = None


class BaseCanonical(BaseModel):
    """Admin envelope shared by every canonical document.

    The LLM may produce ``document_date``, ``language``, ``type`` and ``subtype``;
    these are validated here. Everything else the envelope needs is added by
    Python as metadata (see ``canonical.metadata``).
    """

    model_config = ConfigDict(extra="forbid")

    schema_name: ClassVar[str] = "base"
    subtype: ClassVar[str] = ""

    document_date: str | None = None
    language: str = "ru"
    type: str = "generic"
    subtype_value: str = Field(default="", alias="subtype")

    institution: Institution | None = None
    material: str | None = None
    conclusion: str | None = None

    fields: Any = None


class LaboratoryCanonical(BaseCanonical):
    """Laboratory report: a validated list of measurements."""

    schema_name: ClassVar[str] = "laboratory"
    subtype: ClassVar[str] = "laboratory"

    type: str = "laboratory"
    equipment: str | None = None
    performed_by: list[str] | None = None
    fields: ResultSet | None = None


class PrescriptionCanonical(BaseCanonical):
    """Prescription: medications plus issuing context."""

    schema_name: ClassVar[str] = "prescription"
    subtype: ClassVar[str] = "prescription"

    type: str = "prescription"
    fields: PrescriptionPayload | None = None


class GenericCanonical(BaseCanonical):
    """Default/generic document: a loosely-typed fields dictionary."""

    schema_name: ClassVar[str] = "generic"
    subtype: ClassVar[str] = "generic"

    type: str = "generic"
    fields: dict[str, Any] | None = None


CANONICAL_MODELS: dict[str, type[BaseCanonical]] = {
    LaboratoryCanonical.schema_name: LaboratoryCanonical,
    PrescriptionCanonical.schema_name: PrescriptionCanonical,
    GenericCanonical.schema_name: GenericCanonical,
}

DEFAULT_CANONICAL_MODEL: type[BaseCanonical] = GenericCanonical


def build_canonical(doc_type: str, raw: dict[str, Any]) -> BaseCanonical:
    """Validate a raw LLM payload against the canonical schema for ``doc_type``.

    Falls back to the generic schema for unknown ``doc_type`` values.
    """
    model_cls = CANONICAL_MODELS.get(doc_type, DEFAULT_CANONICAL_MODEL)
    return model_cls.model_validate(raw)
