from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.access import AccessReason, GrantStatus


class AccessGrantCreate(BaseModel):
    account_id: UUID
    organization_id: UUID | None = None
    can_view_documents: bool = False
    can_upload_documents: bool = False
    can_view_extractions: bool = False
    can_view_analytics: bool = False
    can_create_encounters: bool = False
    can_edit_medical_data: bool = False
    access_reason: AccessReason | None = None
    expires_at: datetime | None = None


class AccessGrantUpdate(BaseModel):
    can_view_documents: bool | None = None
    can_upload_documents: bool | None = None
    can_view_extractions: bool | None = None
    can_view_analytics: bool | None = None
    can_create_encounters: bool | None = None
    can_edit_medical_data: bool | None = None
    access_reason: AccessReason | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "AccessGrantUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("at least one field must be set")
        return self


class AccessGrantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    account_id: UUID
    organization_id: UUID | None
    can_view_documents: bool
    can_upload_documents: bool
    can_view_extractions: bool
    can_view_analytics: bool
    can_create_encounters: bool
    can_edit_medical_data: bool
    status: GrantStatus
    granted_at: datetime
    expires_at: datetime | None
    granted_by_account_id: UUID | None
    access_reason: AccessReason | None
    created_at: datetime
    updated_at: datetime
