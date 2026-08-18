from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies.rbac import RbacServiceDep, require_permission
from app.domain.account import PermissionCode
from app.schemas.rbac import (
    AccountRoleAssignRequest,
    AccountRolesResponse,
    PermissionResponse,
    RoleResponse,
)
from app.services.rbac import RoleNotFoundError

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post(
    "/rbac/seed",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission(PermissionCode.USER_MANAGE))],
)
async def seed_rbac(service: RbacServiceDep) -> None:
    await service.seed()


@router.post(
    "/accounts/{account_id}/roles",
    response_model=AccountRolesResponse,
    dependencies=[Depends(require_permission(PermissionCode.USER_MANAGE))],
)
async def assign_account_roles(
    account_id: UUID,
    payload: AccountRoleAssignRequest,
    service: RbacServiceDep,
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
    service: RbacServiceDep,
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
    service: RbacServiceDep,
) -> list[PermissionResponse]:
    permissions = await service.list_account_permissions(account_id)
    return [PermissionResponse.model_validate(permission) for permission in permissions]