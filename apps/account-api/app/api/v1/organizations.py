from uuid import UUID

from fastapi import APIRouter, Request

from app.api.v1.http_errors import raise_for
from app.dependencies.auth import CurrentAccount
from app.dependencies.organization import (
    MyOrganization,
    MyOrganizations,
    OrganizationAdmin,
    OrganizationApiKeyServiceDep,
    OrganizationManager,
    OrganizationServiceDep,
)
from app.domain.organization import (
    OrganizationApiKeyNotFoundError,
    OrganizationBranchConflictError,
    OrganizationBranchNotFoundError,
    OrganizationLegalDataConflictError,
    OrganizationLicenseConflictError,
    OrganizationLicenseNotFoundError,
    OrganizationNotFoundError,
)
from app.schemas.organization import (
    ApiKeyCreate,
    ApiKeyCreateResponse,
    ApiKeyResponse,
    BranchCreate,
    BranchResponse,
    BranchUpdate,
    LicenseCreate,
    LicenseResponse,
    LicenseUpdate,
    OrganizationMemberResponse,
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


@router.get("/me/api-keys", response_model=list[ApiKeyResponse])
async def list_my_api_keys(
    organization: OrganizationAdmin,
    service: OrganizationApiKeyServiceDep,
) -> list[ApiKeyResponse]:
    keys = await service.list_api_keys(organization.id)
    return [ApiKeyResponse.model_validate(key) for key in keys]


@router.post("/me/api-keys", response_model=ApiKeyCreateResponse, status_code=201)
async def create_my_api_key(
    payload: ApiKeyCreate,
    account: CurrentAccount,
    organization: OrganizationAdmin,
    service: OrganizationApiKeyServiceDep,
    request: Request,
) -> ApiKeyCreateResponse:
    key, raw_key = await service.create_api_key(
        organization.id,
        actor_account_id=account.id,
        data=payload,
        request=request,
    )
    return ApiKeyCreateResponse.model_validate(
        {**ApiKeyResponse.model_validate(key).model_dump(), "raw_key": raw_key}
    )


@router.delete("/me/api-keys/{key_id}", status_code=204)
async def revoke_my_api_key(
    key_id: UUID,
    account: CurrentAccount,
    organization: OrganizationAdmin,
    service: OrganizationApiKeyServiceDep,
    request: Request,
) -> None:
    try:
        await service.revoke_api_key(
            organization.id,
            key_id,
            actor_account_id=account.id,
            request=request,
        )
    except OrganizationApiKeyNotFoundError as exc:
        raise_for(exc)


@router.post("/me/api-keys/{key_id}/rotate", response_model=ApiKeyCreateResponse)
async def rotate_my_api_key(
    key_id: UUID,
    account: CurrentAccount,
    organization: OrganizationAdmin,
    service: OrganizationApiKeyServiceDep,
    request: Request,
) -> ApiKeyCreateResponse:
    try:
        key, raw_key = await service.rotate_api_key(
            organization.id,
            key_id,
            actor_account_id=account.id,
            request=request,
        )
    except OrganizationApiKeyNotFoundError as exc:
        raise_for(exc)
    return ApiKeyCreateResponse.model_validate(
        {**ApiKeyResponse.model_validate(key).model_dump(), "raw_key": raw_key}
    )


@router.get("", response_model=list[OrganizationResponse])
async def list_my_organizations(
    organizations: MyOrganizations,
) -> list[OrganizationResponse]:
    """Phase 4b: org-context read — every org with an ACTIVE membership."""
    return [OrganizationResponse.model_validate(org) for org in organizations]


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_my_organization_by_id(
    organization: MyOrganization,
) -> OrganizationResponse:
    """Phase 4b: org-context read — an org the account belongs to (404 otherwise)."""
    return OrganizationResponse.model_validate(organization)


@router.get("/{organization_id}/members", response_model=list[OrganizationMemberResponse])
async def list_my_organization_members(
    organization: OrganizationManager,
    service: OrganizationServiceDep,
) -> list[OrganizationMemberResponse]:
    """Phase 4b: members of MY org (owner|admin); 404 foreign, 403 member role."""
    memberships = await service.list_memberships(organization.id)
    return [OrganizationMemberResponse.model_validate(m) for m in memberships]


__all__ = ["router"]