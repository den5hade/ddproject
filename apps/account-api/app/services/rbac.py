import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.account import PermissionCode, RoleNotFoundError
from app.models.role import Role
from app.repositories.rbac import RbacRepository

logger = logging.getLogger("account_api.rbac")


class RbacService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._rbac = RbacRepository(session)

    async def seed(self) -> None:
        await self._rbac.seed_defaults()
        await self._session.commit()
        logger.info("rbac_seeded")

    async def assign_roles(self, account_id: UUID, role_codes: list[str]) -> list[Role]:
        roles = await self._rbac.assign_roles(account_id, role_codes)
        await self._session.commit()
        logger.info("roles_assigned account_id=%s roles=%s", account_id, role_codes)
        return roles

    async def get_permissions(self, account_id: UUID) -> set[PermissionCode]:
        return await self._rbac.account_permissions(account_id)


__all__ = ["RbacService", "RoleNotFoundError"]
