from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.access import AuditAction


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    actor_account_id: UUID | None
    action: AuditAction
    resource_type: str
    resource_id: UUID | None
    patient_id: UUID | None
    ip_address: str
    user_agent: str
    metadata_: dict | None = Field(default=None, alias="metadata")
    created_at: datetime
