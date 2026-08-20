from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.medical import EncounterStatus, EncounterType


class EncounterCreate(BaseModel):
    type: EncounterType = EncounterType.CONSULTATION
    started_at: datetime
    reason: str | None = None
    summary: str | None = None


class EncounterUpdate(BaseModel):
    status: EncounterStatus | None = None
    ended_at: datetime | None = None
    summary: str | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "EncounterUpdate":
        if not any(
            field is not None
            for field in (self.status, self.ended_at, self.summary)
        ):
            raise ValueError("at least one of status, ended_at, summary must be set")
        return self


class EncounterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    medical_record_id: UUID
    specialist_id: UUID | None
    organization_id: UUID | None
    type: EncounterType
    status: EncounterStatus
    started_at: datetime
    ended_at: datetime | None
    reason: str | None
    summary: str | None
    created_at: datetime
    updated_at: datetime
