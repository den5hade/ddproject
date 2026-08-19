from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.dependencies.auth import CurrentAccount
from app.dependencies.encounter import EncounterServiceDep
from app.domain.medical import (
    DocumentType,
    EncounterAccessDeniedError,
    EncounterNotFoundError,
)
from app.models.document import Document
from app.models.encounter import Encounter
from app.schemas.document import DocumentResponse
from app.schemas.encounter import (
    EncounterCreate,
    EncounterResponse,
    EncounterUpdate,
)

router = APIRouter(tags=["encounters"])


def _encounter_response(encounter: Encounter) -> EncounterResponse:
    return EncounterResponse(
        id=encounter.id,
        medical_record_id=encounter.medical_record_id,
        specialist_id=encounter.specialist_id,
        organization_id=encounter.organization_id,
        type=encounter.type,
        status=encounter.status,
        started_at=encounter.started_at,
        ended_at=encounter.ended_at,
        reason=encounter.reason,
        summary=encounter.summary,
        created_at=encounter.created_at,
        updated_at=encounter.updated_at,
    )


def _document_response(document: Document) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        medical_record_id=document.medical_record_id,
        encounter_id=document.encounter_id,
        document_type=document.document_type or DocumentType.OTHER,
        title=document.title,
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        storage_key=document.storage_key,
        status=document.status,
        uploaded_by_account_id=document.uploaded_by_account_id,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _http_error(exc: Exception) -> HTTPException:
    codes = {
        EncounterNotFoundError: status.HTTP_404_NOT_FOUND,
        EncounterAccessDeniedError: status.HTTP_403_FORBIDDEN,
    }
    return HTTPException(
        status_code=codes.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


@router.post(
    "/patients/{patient_id}/encounters",
    response_model=EncounterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_encounter(
    patient_id: UUID,
    payload: EncounterCreate,
    account: CurrentAccount,
    service: EncounterServiceDep,
) -> EncounterResponse:
    try:
        encounter = await service.create_encounter(account, patient_id, payload)
    except (EncounterNotFoundError, EncounterAccessDeniedError) as exc:
        raise _http_error(exc) from exc
    return _encounter_response(encounter)


@router.get("/patients/{patient_id}/encounters", response_model=list[EncounterResponse])
async def list_encounters(
    patient_id: UUID,
    account: CurrentAccount,
    service: EncounterServiceDep,
) -> list[EncounterResponse]:
    encounters = await service.list_encounters(account, patient_id)
    if encounters is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="patient not found"
        )
    return [_encounter_response(encounter) for encounter in encounters]


@router.get("/encounters/{encounter_id}", response_model=EncounterResponse)
async def get_encounter(
    encounter_id: UUID,
    account: CurrentAccount,
    service: EncounterServiceDep,
) -> EncounterResponse:
    try:
        encounter = await service.get_encounter(account, encounter_id)
    except (EncounterNotFoundError, EncounterAccessDeniedError) as exc:
        raise _http_error(exc) from exc
    return _encounter_response(encounter)


@router.patch("/encounters/{encounter_id}", response_model=EncounterResponse)
async def update_encounter(
    encounter_id: UUID,
    payload: EncounterUpdate,
    account: CurrentAccount,
    service: EncounterServiceDep,
) -> EncounterResponse:
    try:
        encounter = await service.update_encounter(account, encounter_id, payload)
    except (EncounterNotFoundError, EncounterAccessDeniedError) as exc:
        raise _http_error(exc) from exc
    return _encounter_response(encounter)


@router.get(
    "/encounters/{encounter_id}/documents", response_model=list[DocumentResponse]
)
async def list_encounter_documents(
    encounter_id: UUID,
    account: CurrentAccount,
    service: EncounterServiceDep,
) -> list[DocumentResponse]:
    try:
        documents = await service.list_encounter_documents(account, encounter_id)
    except (EncounterNotFoundError, EncounterAccessDeniedError) as exc:
        raise _http_error(exc) from exc
    return [_document_response(document) for document in documents]
