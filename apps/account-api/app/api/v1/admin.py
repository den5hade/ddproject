from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies.rbac import get_rbac_service, require_permission
from app.domain.account import PermissionCode
from app.schemas.rbac import (
    AccountRoleAssignRequest,
    AccountRolesResponse,
    PermissionResponse,
    RoleResponse,
)
from app.services.rbac import RbacService, RoleNotFoundError

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post(
    "/rbac/seed",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission(PermissionCode.USER_MANAGE))],
)
async def seed_rbac(service: RbacService = Depends(get_rbac_service)) -> None:
    await service.seed()


@router.post(
    "/accounts/{account_id}/roles",
    response_model=AccountRolesResponse,
    dependencies=[Depends(require_permission(PermissionCode.USER_MANAGE))],
)
async def assign_account_roles(
    account_id: UUID,
    payload: AccountRoleAssignRequest,
    service: RbacService = Depends(get_rbac_service),
) -> AccountRolesResponse:
    try:
        roles = await service.assign_roles(account_id, payload.role_codes)
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return AccountRolesResponse(
        account_id=account_id,
        roles=[RoleResponse.model_validate(role) for role in roles],
    )


@router.get(
    "/accounts/{account_id}/roles",
    response_model=AccountRolesResponse,
    dependencies=[Depends(require_permission(PermissionCode.USER_MANAGE))],
)
async def list_account_roles(
    account_id: UUID,
    service: RbacService = Depends(get_rbac_service),
) -> AccountRolesResponse:
    roles = await service.list_account_roles(account_id)
    return AccountRolesResponse(
        account_id=account_id,
        roles=[RoleResponse.model_validate(role) for role in roles],
    )


@router.get(
    "/accounts/{account_id}/permissions",
    response_model=list[PermissionResponse],
    dependencies=[Depends(require_permission(PermissionCode.USER_MANAGE))],
)
async def list_account_permissions(
    account_id: UUID,
    service: RbacService = Depends(get_rbac_service),
) -> list[PermissionResponse]:
    permissions = await service.list_account_permissions(account_id)
    return [PermissionResponse.model_validate(permission) for permission in permissions]
