from uuid import UUID

from pydantic import BaseModel

from app.domain.medical import PatientStatus
from app.schemas.profile import PersonResponse, PersonUpdate


class PatientCreateRequest(BaseModel):
    person: PersonUpdate | None = None


class PatientResponse(BaseModel):
    id: UUID
    person: PersonResponse
    medical_record_id: UUID
    status: PatientStatus