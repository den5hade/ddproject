from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.v1.http_errors import raise_for
from app.dependencies.organization import OrganizationServiceDep
from app.dependencies.rbac import require_roles
from app.domain.account import RoleCode
from app.domain.organization import (
    OrganizationLegalDataConflictError,
    OrganizationMembershipConflictError,
    OrganizationNotFoundError,
)
from app.models.account import Account
from app.schemas.organization import (
    OrganizationAdminCreate,
    OrganizationMemberCreate,
    OrganizationMemberResponse,
    OrganizationResponse,
)

router = APIRouter(prefix="/admin/organizations", tags=["admin-organizations"])

SystemAdmin = Annotated[Account, Depends(require_roles(RoleCode.SYSTEM_ADMIN))]


@router.post("", response_model=OrganizationResponse, status_code=201)
async def create_onboarded_organization(
    payload: OrganizationAdminCreate,
    account: SystemAdmin,
    service: OrganizationServiceDep,
    request: Request,
) -> OrganizationResponse:
    try:
        organization = await service.admin_create_organization(
            account.id, data=payload, request=request
        )
    except (OrganizationNotFoundError, OrganizationLegalDataConflictError) as exc:
        raise_for(exc)
    return OrganizationResponse.model_validate(organization)


@router.get("", response_model=list[OrganizationResponse])
async def list_all_organizations(
    _admin: SystemAdmin,
    service: OrganizationServiceDep,
) -> list[OrganizationResponse]:
    organizations = await service.list_organizations()
    return [OrganizationResponse.model_validate(org) for org in organizations]


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: UUID,
    _admin: SystemAdmin,
    service: OrganizationServiceDep,
) -> OrganizationResponse:
    try:
        organization = await service.get_organization(organization_id)
    except OrganizationNotFoundError as exc:
        raise_for(exc)
    return OrganizationResponse.model_validate(organization)


@router.post(
    "/{organization_id}/members",
    response_model=OrganizationMemberResponse,
    status_code=201,
)
async def add_organization_member(
    organization_id: UUID,
    payload: OrganizationMemberCreate,
    account: SystemAdmin,
    service: OrganizationServiceDep,
    request: Request,
) -> OrganizationMemberResponse:
    try:
        membership = await service.admin_attach_membership(
            account.id, organization_id, data=payload, request=request
        )
    except (
        OrganizationNotFoundError,
        OrganizationMembershipConflictError,
    ) as exc:
        raise_for(exc)
    return OrganizationMemberResponse.model_validate(membership)


@router.get("/{organization_id}/members", response_model=list[OrganizationMemberResponse])
async def list_organization_members(
    organization_id: UUID,
    _admin: SystemAdmin,
    service: OrganizationServiceDep,
) -> list[OrganizationMemberResponse]:
    try:
        memberships = await service.list_memberships(organization_id)
    except OrganizationNotFoundError as exc:
        raise_for(exc)
    return [OrganizationMemberResponse.model_validate(m) for m in memberships]


__all__ = ["router"]