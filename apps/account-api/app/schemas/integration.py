from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.core.timezone import to_api_tz
from app.domain.account import IdentityKind
from app.domain.identity import Identity
from app.domain.medical import DocumentStatus, DocumentType


def normalize_patient_email(v: object) -> str:
    """Integration ``patient_email``: identity-validated, email-only, lowercase."""
    if v is None or str(v).strip() == "":
        raise ValueError("patient_email is required")
    parsed = Identity.parse(str(v))
    if parsed.kind is not IdentityKind.EMAIL:
        raise ValueError("patient identity must be an email address")
    return parsed.canonical


def _blank_to_none(v: object) -> str | None:
    if v is None:
        return None
    value = str(v).strip()
    return value or None


class IntegrationDocumentSubmit(BaseModel):
    """Multipart form fields accompanying the integration document upload."""

    patient_email: str = Field(max_length=255)
    document_type: DocumentType = DocumentType.OTHER
    external_id: str | None = Field(default=None, min_length=1, max_length=255)
    branch_code: str | None = Field(default=None, min_length=1, max_length=32)
    title: str | None = Field(default=None, max_length=512)

    @field_validator("patient_email", mode="before")
    @classmethod
    def _email(cls, v: object) -> str:
        return normalize_patient_email(v)

    @field_validator("external_id", "branch_code", mode="before")
    @classmethod
    def _blank(cls, v: object) -> str | None:
        return _blank_to_none(v)


class IntegrationDocumentResponse(BaseModel):
    """POST /integration/documents acknowledgment (Phase 4d, §4.8)."""

    document_id: UUID
    status: Literal["processing"] = "processing"
    external_id: str | None = None
    patient_id: UUID


class IntegrationDocumentStatusResponse(BaseModel):
    """GET /integration/documents/{id} current state of an org-submitted document."""

    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    status: DocumentStatus
    document_type: DocumentType
    external_id: str | None
    organization_id: UUID
    document_date: datetime | None = None
    created_at: datetime

    @field_serializer("document_date", "created_at")
    def _tz(self, v: datetime | None) -> datetime | None:
        return to_api_tz(v) if v is not None else None