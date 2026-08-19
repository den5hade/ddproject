from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies.access import AccessServiceDep, require_patient_owner
from app.dependencies.auth import CurrentAccount
from app.domain.access import PatientAccessGrantNotFoundError
from app.models.access_grant import PatientAccessGrant
from app.schemas.access import (
    AccessGrantCreate,
    AccessGrantResponse,
    AccessGrantUpdate,
)

router = APIRouter(tags=["access"])


def _grant_response(grant: PatientAccessGrant) -> AccessGrantResponse:
    return AccessGrantResponse.model_validate(grant)


def _http_error(exc: Exception) -> HTTPException:
    codes = {
        PatientAccessGrantNotFoundError: status.HTTP_404_NOT_FOUND,
    }
    return HTTPException(
        status_code=codes.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


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
    return _grant_response(grant)


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
    return [_grant_response(grant) for grant in grants]


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
        raise _http_error(exc) from exc
    return _grant_response(grant)


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
        raise _http_error(exc) from exc
    return _grant_response(grant)
