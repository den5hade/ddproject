from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.v1.http_errors import raise_for
from app.dependencies.access import AccessServiceDep, require_patient_owner
from app.dependencies.auth import CurrentAccount
from app.domain.access import PatientAccessGrantNotFoundError
from app.schemas.access import (
    AccessGrantCreate,
    AccessGrantResponse,
    AccessGrantUpdate,
)

router = APIRouter(tags=["access"])


@router.post(
    "/patients/{patient_id}/access-grants",
    response_model=AccessGrantResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_patient_owner())],
)
async def create_access_grant(
    patient_id: UUID,
    payload: AccessGrantCreate,
    account: CurrentAccount,
    service: AccessServiceDep,
) -> AccessGrantResponse:
    grant = await service.grant(actor=account, patient_id=patient_id, data=payload)
    return AccessGrantResponse.model_validate(grant)


@router.get(
    "/patients/{patient_id}/access-grants",
    response_model=list[AccessGrantResponse],
    dependencies=[Depends(require_patient_owner())],
)
async def list_access_grants(
    patient_id: UUID,
    service: AccessServiceDep,
) -> list[AccessGrantResponse]:
    grants = await service.list_grants(patient_id=patient_id)
    return [AccessGrantResponse.model_validate(g) for g in grants]


@router.patch(
    "/patients/{patient_id}/access-grants/{grant_id}",
    response_model=AccessGrantResponse,
    dependencies=[Depends(require_patient_owner())],
)
async def update_access_grant(
    patient_id: UUID,
    grant_id: UUID,
    payload: AccessGrantUpdate,
    account: CurrentAccount,
    service: AccessServiceDep,
) -> AccessGrantResponse:
    try:
        grant = await service.update_grant(
            actor=account, patient_id=patient_id, grant_id=grant_id, data=payload
        )
    except PatientAccessGrantNotFoundError as exc:
        raise_for(exc)
    return AccessGrantResponse.model_validate(grant)


@router.delete(
    "/patients/{patient_id}/access-grants/{grant_id}",
    response_model=AccessGrantResponse,
    dependencies=[Depends(require_patient_owner())],
)
async def revoke_access_grant(
    patient_id: UUID,
    grant_id: UUID,
    account: CurrentAccount,
    service: AccessServiceDep,
) -> AccessGrantResponse:
    try:
        grant = await service.revoke(
            actor=account, patient_id=patient_id, grant_id=grant_id
        )
    except PatientAccessGrantNotFoundError as exc:
        raise_for(exc)
    return AccessGrantResponse.model_validate(grant)
