"""Schema resolution contract (Classification 2.0).

Locks the ``(document_type, document_subtype) -> schema_key`` mapping and the
``SchemaResolver`` protocol. No runtime resolution logic is required to
execute in M1; the mapping shape is the contract.
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


class SchemaResolver(Protocol):
    """Protocol for resolvers that map a classification to a schema key."""

    def resolve(
        self,
        document_type: DocumentType,
        document_subtype: str | None = None,
    ) -> str:
        """Resolve ``document_type``/``document_subtype`` to a schema key.

        Contract only — no implementation in M1.
        """
        ...


__all__ = ["SCHEMA_REGISTRY", "SchemaResolver"]