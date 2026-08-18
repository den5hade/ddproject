from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_account
from app.domain.account import PermissionCode, RoleCode
from app.models.account import Account
from app.repositories.rbac import RbacRepository
from app.services.rbac import RbacService


async def get_rbac_service(session: AsyncSession = Depends(get_db)) -> RbacService:
    return RbacService(session)


def require_roles(*codes: RoleCode) -> Callable[..., Account]:
    """Return a dependency requiring the current account to hold at least one role."""

    async def dependency(
        account: Account = Depends(get_current_account),
        session: AsyncSession = Depends(get_db),
    ) -> Account:
        roles = await RbacRepository(session).list_account_roles(account.id)
        account_codes = {role.code for role in roles}
        required = {code.value for code in codes}
        if not account_codes.intersection(required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="insufficient roles"
            )
        return account

    return dependency


def require_permission(code: PermissionCode) -> Callable[..., Account]:
    """Return a dependency requiring the current account to hold the permission."""

    async def dependency(
        account: Account = Depends(get_current_account),
        session: AsyncSession = Depends(get_db),
    ) -> Account:
        permissions = await RbacRepository(session).account_permissions(account.id)
        if code not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="insufficient permissions"
            )
        return account

    return dependency


RbacServiceDep = Annotated[RbacService, Depends(get_rbac_service)]
