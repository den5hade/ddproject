from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.dependencies.auth import CurrentAccount
from app.dependencies.patient import PatientServiceDep
from app.domain.medical import PatientAlreadyExistsError, PersonNotFoundError
from app.schemas.patient import PatientCreateRequest, PatientResponse
from app.schemas.profile import PersonUpdate
from app.services.patient import PatientContext

router = APIRouter(prefix="/patients", tags=["patients"])


def _to_response(context: PatientContext) -> PatientResponse:
    return PatientResponse(
        id=context.patient.id,
        person=context.person,
        medical_record_id=context.medical_record.id,
        status=context.patient.status,
    )


@router.post("", response_model=PatientResponse, status_code=status.HTTP_201_CREATED)
async def create_patient(
    account: CurrentAccount,
    service: PatientServiceDep,
    payload: PatientCreateRequest | None = None,
) -> PatientResponse:
    try:
        context = await service.create_patient(account, payload)
    except PatientAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return _to_response(context)


@router.get("/me", response_model=PatientResponse)
async def get_my_patient(
    account: CurrentAccount,
    service: PatientServiceDep,
) -> PatientResponse:
    return _to_response(await service.get_patient(account))


@router.patch("/me", response_model=PatientResponse)
async def update_my_person(
    payload: PersonUpdate,
    account: CurrentAccount,
    service: PatientServiceDep,
) -> PatientResponse:
    try:
        context = await service.update_person(account, payload)
    except PersonNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _to_response(context)


@router.get("/{patient_id}", response_model=PatientResponse)
async def get_patient(
    patient_id: UUID,
    account: CurrentAccount,
    service: PatientServiceDep,
) -> PatientResponse:
    context = await service.get_patient_for_view(account, patient_id)
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="patient not found"
        )
    return _to_response(context)