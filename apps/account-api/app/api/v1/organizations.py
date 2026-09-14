from fastapi import APIRouter, Request

from app.api.v1.http_errors import raise_for
from app.dependencies.auth import CurrentAccount
from app.dependencies.organization import OrganizationAdmin, OrganizationServiceDep
from app.domain.organization import (
    OrganizationLegalDataConflictError,
    OrganizationNotFoundError,
)
from app.schemas.organization import OrganizationResponse, OrganizationUpdate

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("/me", response_model=OrganizationResponse)
async def get_my_organization(
    organization: OrganizationAdmin,
) -> OrganizationResponse:
    return OrganizationResponse.model_validate(organization)


@router.patch("/me", response_model=OrganizationResponse)
async def update_my_organization(
    payload: OrganizationUpdate,
    account: CurrentAccount,
    organization: OrganizationAdmin,
    service: OrganizationServiceDep,
    request: Request,
) -> OrganizationResponse:
    try:
        updated = await service.update_organization(
            organization.id,
            actor_account_id=account.id,
            data=payload,
            request=request,
        )
    except (OrganizationNotFoundError, OrganizationLegalDataConflictError) as exc:
        raise_for(exc)
    return OrganizationResponse.model_validate(updated)


__all__ = ["router"]