from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer

from app.core.timezone import to_api_tz
from app.domain.medical import (
    DocumentStatus,
    DocumentType,
    ExtractionStatus,
    ProcessingJobStatus,
    ProcessingJobType,
)


class DocumentCreateRequest(BaseModel):
    """Multipart form fields alongside the uploaded binary."""

    document_type: DocumentType = DocumentType.OTHER
    title: str = ""
    encounter_id: UUID | None = None


class DocumentVersionCreateRequest(BaseModel):
    """Multipart form fields for adding a version; versions never re-route."""

    document_type: DocumentType = DocumentType.OTHER
    title: str = ""


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    medical_record_id: UUID
    encounter_id: UUID | None
    document_type: DocumentType
    title: str
    original_filename: str
    mime_type: str
    size_bytes: int
    storage_key: str
    status: DocumentStatus
    document_date: datetime | None = None
    uploaded_by_account_id: UUID | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at", "document_date")
    def _tz(self, v: datetime | None) -> datetime | None:
        return to_api_tz(v) if v is not None else None


class DocumentVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    version: int
    s3_key: str
    mime_type: str
    size_bytes: int
    checksum: str | None
    created_by_account_id: UUID | None
    created_at: datetime

    @field_serializer("created_at")
    def _tz(self, v: datetime) -> datetime | None:
        return to_api_tz(v)


class DocumentExtractionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    document_version_id: UUID | None
    schema_name: str
    schema_version: str
    status: ExtractionStatus
    confidence: float | None
    data: dict | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _tz(self, v: datetime) -> datetime | None:
        return to_api_tz(v)


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    document_version_id: UUID | None
    job_type: ProcessingJobType
    status: ProcessingJobStatus
    attempts: int
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at", "started_at", "finished_at")
    def _tz(self, v: datetime) -> datetime | None:
        return to_api_tz(v)


class DownloadUrlResponse(BaseModel):
    download_url: str
    expires_in: int


class MarkdownResponse(BaseModel):
    """Markdown artifacts (unstructured/structured) for a document version."""

    unstructured_key: str | None = None
    structured_key: str | None = None
    unstructured_url: str | None = None
    structured_url: str | None = None
    has_unstructured: bool = False
    has_structured: bool = False


class CanonicalResponse(BaseModel):
    """Inline parsed canonical JSON + rendered markdown for a document version.

    ``canonical.json`` is the single source of truth from the ai-worker; the
    rendered markdown is the deterministic Python `structured.md` view.
    """

    canonical: dict | None = None
    canonical_key: str | None = None
    structured_markdown: str | None = None
    has_canonical: bool = False


class CanonicalDataResponse(BaseModel):
    """Persisted canonical data (latest succeeded extraction) for a document.

    ``data`` mirrors ``document_extractions.data`` and includes the canonical
    object plus ``canonical_key`` / ``structured_key``.
    """

    schema_name: str
    schema_version: str
    confidence: float | None = None
    data: dict
