from uuid import UUID

EXTENSION_BY_MIME = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/tiff": "tiff",
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