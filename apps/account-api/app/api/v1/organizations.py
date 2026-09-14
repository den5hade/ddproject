from uuid import UUID

from fastapi import APIRouter, Request

from app.api.v1.http_errors import raise_for
from app.dependencies.auth import CurrentAccount
from app.dependencies.organization import OrganizationAdmin, OrganizationServiceDep
from app.domain.organization import (
    OrganizationBranchConflictError,
    OrganizationBranchNotFoundError,
    OrganizationLegalDataConflictError,
    OrganizationLicenseConflictError,
    OrganizationLicenseNotFoundError,
    OrganizationNotFoundError,
)
from app.schemas.organization import (
    BranchCreate,
    BranchResponse,
    BranchUpdate,
    LicenseCreate,
    LicenseResponse,
    LicenseUpdate,
    OrganizationResponse,
    OrganizationUpdate,
)

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


@router.get("/me/branches", response_model=list[BranchResponse])
async def list_my_branches(
    service: OrganizationServiceDep,
    organization: OrganizationAdmin,
) -> list[BranchResponse]:
    branches = await service.list_branches(organization.id)
    return [BranchResponse.model_validate(b) for b in branches]


@router.post("/me/branches", response_model=BranchResponse, status_code=201)
async def create_my_branch(
    payload: BranchCreate,
    account: CurrentAccount,
    organization: OrganizationAdmin,
    service: OrganizationServiceDep,
    request: Request,
) -> BranchResponse:
    try:
        branch = await service.create_branch(
            organization.id,
            actor_account_id=account.id,
            data=payload,
            request=request,
        )
    except (OrganizationBranchNotFoundError, OrganizationBranchConflictError) as exc:
        raise_for(exc)
    return BranchResponse.model_validate(branch)


@router.get("/me/branches/{branch_id}", response_model=BranchResponse)
async def get_my_branch(
    branch_id: UUID,
    organization: OrganizationAdmin,
    service: OrganizationServiceDep,
) -> BranchResponse:
    try:
        branch = await service.get_branch(organization.id, branch_id)
    except OrganizationBranchNotFoundError as exc:
        raise_for(exc)
    return BranchResponse.model_validate(branch)


@router.patch("/me/branches/{branch_id}", response_model=BranchResponse)
async def update_my_branch(
    branch_id: UUID,
    payload: BranchUpdate,
    account: CurrentAccount,
    organization: OrganizationAdmin,
    service: OrganizationServiceDep,
    request: Request,
) -> BranchResponse:
    try:
        branch = await service.update_branch(
            organization.id,
            branch_id,
            actor_account_id=account.id,
            data=payload,
            request=request,
        )
    except (OrganizationBranchNotFoundError, OrganizationBranchConflictError) as exc:
        raise_for(exc)
    return BranchResponse.model_validate(branch)


@router.delete("/me/branches/{branch_id}", status_code=204)
async def deactivate_my_branch(
    branch_id: UUID,
    account: CurrentAccount,
    organization: OrganizationAdmin,
    service: OrganizationServiceDep,
    request: Request,
) -> None:
    try:
        await service.deactivate_branch(
            organization.id,
            branch_id,
            actor_account_id=account.id,
            request=request,
        )
    except OrganizationBranchNotFoundError as exc:
        raise_for(exc)


@router.get("/me/licenses", response_model=list[LicenseResponse])
async def list_my_licenses(
    organization: OrganizationAdmin,
    service: OrganizationServiceDep,
) -> list[LicenseResponse]:
    licenses = await service.list_licenses(organization.id)
    return [LicenseResponse.model_validate(item) for item in licenses]


@router.post("/me/licenses", response_model=LicenseResponse, status_code=201)
async def create_my_license(
    payload: LicenseCreate,
    account: CurrentAccount,
    organization: OrganizationAdmin,
    service: OrganizationServiceDep,
    request: Request,
) -> LicenseResponse:
    try:
        license = await service.create_license(
            organization.id,
            actor_account_id=account.id,
            data=payload,
            request=request,
        )
    except OrganizationLicenseConflictError as exc:
        raise_for(exc)
    return LicenseResponse.model_validate(license)


@router.get("/me/licenses/{license_id}", response_model=LicenseResponse)
async def get_my_license(
    license_id: UUID,
    organization: OrganizationAdmin,
    service: OrganizationServiceDep,
) -> LicenseResponse:
    try:
        license = await service.get_license(organization.id, license_id)
    except OrganizationLicenseNotFoundError as exc:
        raise_for(exc)
    return LicenseResponse.model_validate(license)


@router.patch("/me/licenses/{license_id}", response_model=LicenseResponse)
async def update_my_license(
    license_id: UUID,
    payload: LicenseUpdate,
    account: CurrentAccount,
    organization: OrganizationAdmin,
    service: OrganizationServiceDep,
    request: Request,
) -> LicenseResponse:
    try:
        license = await service.update_license(
            organization.id,
            license_id,
            actor_account_id=account.id,
            data=payload,
            request=request,
        )
    except (
        OrganizationLicenseNotFoundError,
        OrganizationLicenseConflictError,
    ) as exc:
        raise_for(exc)
    return LicenseResponse.model_validate(license)


@router.delete("/me/licenses/{license_id}", status_code=204)
async def deactivate_my_license(
    license_id: UUID,
    account: CurrentAccount,
    organization: OrganizationAdmin,
    service: OrganizationServiceDep,
    request: Request,
) -> None:
    try:
        await service.deactivate_license(
            organization.id,
            license_id,
            actor_account_id=account.id,
            request=request,
        )
    except OrganizationLicenseNotFoundError as exc:
        raise_for(exc)


__all__ = ["router"]