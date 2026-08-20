from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.v1.http_errors import raise_for
from app.dependencies.access import require_encounter_access, require_patient_access
from app.dependencies.auth import CurrentAccount
from app.dependencies.encounter import EncounterServiceDep
from app.domain.access import AuditAction
from app.domain.medical import (
    EncounterNotFoundError,
)
from app.schemas.document import DocumentResponse
from app.schemas.encounter import (
    EncounterCreate,
    EncounterResponse,
    EncounterUpdate,
)

router = APIRouter(tags=["encounters"])


@router.post(
    "/patients/{patient_id}/encounters",
    response_model=EncounterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(
            require_patient_access(
                can_create_encounters=True, action=AuditAction.CREATE_ENCOUNTER
            )
        )
    ],
)
async def create_encounter(
    patient_id: UUID,
    payload: EncounterCreate,
    account: CurrentAccount,
    service: EncounterServiceDep,
) -> EncounterResponse:
    try:
        encounter = await service.create_encounter(account, patient_id, payload)
    except EncounterNotFoundError as exc:
        raise_for(exc)
    return EncounterResponse.model_validate(encounter)


@router.get(
    "/patients/{patient_id}/encounters",
    response_model=list[EncounterResponse],
    dependencies=[
        Depends(
            require_patient_access(
                action=AuditAction.VIEW_MEDICAL_RECORD,
                deny_status=status.HTTP_404_NOT_FOUND,
            )
        )
    ],
)
async def list_encounters(
    patient_id: UUID,
    service: EncounterServiceDep,
) -> list[EncounterResponse]:
    try:
        encounters = await service.list_encounters(patient_id)
    except EncounterNotFoundError as exc:
        raise_for(exc)
    return [EncounterResponse.model_validate(e) for e in encounters]


@router.get(
    "/encounters/{encounter_id}",
    response_model=EncounterResponse,
    dependencies=[
        Depends(
            require_encounter_access(action=AuditAction.VIEW_MEDICAL_RECORD)
        )
    ],
)
async def get_encounter(
    encounter_id: UUID,
    service: EncounterServiceDep,
) -> EncounterResponse:
    try:
        encounter = await service.get_encounter(encounter_id)
    except EncounterNotFoundError as exc:
        raise_for(exc)
    return EncounterResponse.model_validate(encounter)


@router.patch(
    "/encounters/{encounter_id}",
    response_model=EncounterResponse,
    dependencies=[
        Depends(
            require_encounter_access(
                flag="can_edit_medical_data", action=AuditAction.UPDATE_ENCOUNTER
            )
        )
    ],
)
async def update_encounter(
    encounter_id: UUID,
    payload: EncounterUpdate,
    service: EncounterServiceDep,
) -> EncounterResponse:
    try:
        encounter = await service.update_encounter(encounter_id, payload)
    except EncounterNotFoundError as exc:
        raise_for(exc)
    return EncounterResponse.model_validate(encounter)


@router.get(
    "/encounters/{encounter_id}/documents",
    response_model=list[DocumentResponse],
    dependencies=[
        Depends(require_encounter_access(action=AuditAction.VIEW_DOCUMENT))
    ],
)
async def list_encounter_documents(
    encounter_id: UUID,
    service: EncounterServiceDep,
) -> list[DocumentResponse]:
    try:
        documents = await service.list_encounter_documents(encounter_id)
    except EncounterNotFoundError as exc:
        raise_for(exc)
    return [DocumentResponse.model_validate(d) for d in documents]
