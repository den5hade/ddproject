from uuid import UUID

from contracts.schemas.events import DocumentEvent


class DocumentUploadRequested(DocumentEvent):
    """account-api → objectstorage-worker: binary is staged in the shared temp dir."""

    tenant_id: str
    medical_record_id: UUID
    temp_path: str
    original_filename: str
    mime_type: str
    size_bytes: int