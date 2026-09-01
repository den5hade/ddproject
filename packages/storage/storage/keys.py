from uuid import UUID

EXTENSION_BY_MIME = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/tiff": "tiff",
}

MARKDOWN_ARTIFACTS = {
    "unstructured": "marker.md",
    "structured": "structured.md",
    "canonical": "canonical.json",
}


def build_key(
    tenant_id: str,
    patient_id: UUID,
    document_id: UUID,
    version_id: UUID,
    filename: str,
) -> str:
    """Immutable-id key layout: never rename files, never expose user-derived names."""
    return (
        f"tenants/{tenant_id}/patients/{patient_id}"
        f"/documents/{document_id}/versions/{version_id}/{filename}"
    )


def original_filename_for(mime_type: str) -> str:
    extension = EXTENSION_BY_MIME.get(mime_type, "bin")
    return f"original.{extension}"


def markdown_artifact_filename(kind: str) -> str:
    """Return the canonical filename for a markdown artifact.

    ``kind`` is one of ``"unstructured"`` (marker.md), ``"structured"``
    (structured.md), or ``"canonical"`` (canonical.json). Unknown kinds raise
    ``ValueError``.
    """
    try:
        return MARKDOWN_ARTIFACTS[kind]
    except KeyError:
        raise ValueError(f"unknown markdown artifact: {kind}") from None


def markdown_key(
    *,
    tenant_id: str,
    patient_id: UUID,
    document_id: UUID,
    version_id: UUID,
    kind: str,
) -> str:
    """Build the immutable S3 key for a converted (unstructured) or structured markdown file."""
    return build_key(
        tenant_id,
        patient_id,
        document_id,
        version_id,
        markdown_artifact_filename(kind),
    )
