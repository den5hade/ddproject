from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

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
    uploaded_by_account_id: UUID | None
    created_at: datetime
    updated_at: datetime


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


class DownloadUrlResponse(BaseModel):
    download_url: str
    expires_in: int
