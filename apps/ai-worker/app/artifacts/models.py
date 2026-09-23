"""Artifact models: object keys and storage kind constants."""

from storage import (
    MARKDOWN_KIND_CANONICAL,
    MARKDOWN_KIND_CLASSIFICATION,
    MARKDOWN_KIND_STRUCTURED,
    MARKDOWN_KIND_UNSTRUCTURED,
    markdown_key,
)

__all__ = [
    "MARKDOWN_KIND_CANONICAL",
    "MARKDOWN_KIND_CLASSIFICATION",
    "MARKDOWN_KIND_STRUCTURED",
    "MARKDOWN_KIND_UNSTRUCTURED",
    "build_markdown_key",
]


def build_markdown_key(
    *,
    tenant_id: str,
    patient_id,
    document_id,
    version_id,
    kind: str,
) -> str:
    """Build the markdown artifact object key for a document version."""
    if not version_id:
        return ""
    return markdown_key(
        tenant_id=tenant_id,
        patient_id=patient_id,
        document_id=document_id,
        version_id=version_id,
        kind=kind,
    )