"""Schema resolution contract (Classification 2.0).

Locks the ``(document_type, document_subtype) -> schema_key`` mapping
(``SCHEMA_REGISTRY``) and the ``SchemaResolver`` protocol. M2 adds the concrete
``RegistrySchemaResolver`` that looks up a prompt key (canonical extraction
template) for a classification, applying an intermediate
``schema_key -> prompt_key`` translation.

Available extraction schemas map to prompt templates as follows:
``laboratory.v1`` -> ``laboratory``, ``prescription.v1`` -> ``prescription``,
``generic.v1`` -> ``default``, ``appointment.v1`` -> ``default`` (fallback until
a canonical appointment schema exists — classification metadata still records
the ``appointment`` document type).
"""

from typing import Protocol

from app.classification.models import DocumentType

SCHEMA_REGISTRY: dict[tuple[str, str | None], str] = {
    ("laboratory", "hematology"): "laboratory.v1",
    ("laboratory", None): "laboratory.v1",
    ("appointment", None): "appointment.v1",
    ("prescription", None): "prescription.v1",
    ("other", None): "generic.v1",
    # Contract only: discharge/diagnosis/imaging/consultation map to
    # "generic.v1" until specialized canonical schemas exist.
    ("discharge", None): "generic.v1",
    ("diagnosis", None): "generic.v1",
    ("imaging", None): "generic.v1",
    ("consultation", None): "generic.v1",
}
"""Locked mapping of ``(document_type, document_subtype)`` to canonical schema keys."""

SCHEMA_PROMPT_KEY: dict[str, str] = {
    "laboratory.v1": "laboratory",
    "prescription.v1": "prescription",
    "generic.v1": "default",
    "appointment.v1": "default",
}
"""Mapping of canonical schema key to the canonical extraction prompt key."""


class SchemaResolver(Protocol):
    """Protocol for resolvers that map a classification to a schema key."""

    def resolve(
        self,
        document_type: DocumentType,
        document_subtype: str | None = None,
    ) -> str:
        """Resolve ``document_type``/``document_subtype`` to a prompt key."""
        ...


class RegistrySchemaResolver:
    """Resolve a classification to the canonical extraction prompt key."""

    def resolve(
        self,
        document_type: DocumentType,
        document_subtype: str | None = None,
    ) -> str:
        value = (
            document_type.value
            if isinstance(document_type, DocumentType)
            else str(document_type)
        )
        schema_key = SCHEMA_REGISTRY.get(
            (value, document_subtype),
            SCHEMA_REGISTRY.get((value, None), SCHEMA_REGISTRY[("other", None)]),
        )
        return SCHEMA_PROMPT_KEY.get(schema_key, "default")


__all__ = ["SCHEMA_PROMPT_KEY", "SCHEMA_REGISTRY", "RegistrySchemaResolver", "SchemaResolver"]