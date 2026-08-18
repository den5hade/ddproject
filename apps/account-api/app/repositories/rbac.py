from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.account import (
    PermissionCode,
    RoleCode,
    RoleNotFoundError,
)
from app.models.role import AccountRole, Permission, Role, RolePermission

ROLE_NAMES: dict[RoleCode, str] = {
    RoleCode.CLIENT: "Client",
    RoleCode.SPECIALIST: "Specialist",
    RoleCode.ORGANIZATION_ADMIN: "Organization admin",
    RoleCode.SYSTEM_ADMIN: "System admin",
    RoleCode.SUPPORT: "Support",
}

PERMISSION_NAMES: dict[PermissionCode, str] = {
    PermissionCode.MEDICAL_RECORD_READ: "Read medical record",
    PermissionCode.MEDICAL_RECORD_WRITE: "Write medical record",
    PermissionCode.DOCUMENT_READ: "Read documents",
    PermissionCode.DOCUMENT_UPLOAD: "Upload documents",
    PermissionCode.DOCUMENT_DOWNLOAD: "Download documents",
    PermissionCode.ENCOUNTER_READ: "Read encounters",
    PermissionCode.ENCOUNTER_CREATE: "Create encounters",
    PermissionCode.ENCOUNTER_UPDATE: "Update encounters",
    PermissionCode.ANALYTICS_READ: "Read analytics",
    PermissionCode.USER_MANAGE: "Manage users",
    PermissionCode.ORGANIZATION_MANAGE: "Manage organizations",
}

ROLE_PERMISSIONS: dict[RoleCode, set[PermissionCode]] = {
    RoleCode.CLIENT: {
        PermissionCode.MEDICAL_RECORD_READ,
        PermissionCode.DOCUMENT_READ,
        PermissionCode.DOCUMENT_UPLOAD,
        PermissionCode.DOCUMENT_DOWNLOAD,
    },
    RoleCode.SPECIALIST: {
        PermissionCode.MEDICAL_RECORD_READ,
        PermissionCode.MEDICAL_RECORD_WRITE,
        PermissionCode.DOCUMENT_READ,
        PermissionCode.DOCUMENT_UPLOAD,
        PermissionCode.DOCUMENT_DOWNLOAD,
        PermissionCode.ENCOUNTER_READ,
        PermissionCode.ENCOUNTER_CREATE,
        PermissionCode.ENCOUNTER_UPDATE,
        PermissionCode.ANALYTICS_READ,
    },
    RoleCode.ORGANIZATION_ADMIN: {
        PermissionCode.ORGANIZATION_MANAGE,
    },
    RoleCode.SYSTEM_ADMIN: set(PermissionCode),
    RoleCode.SUPPORT: set(),
}


class RbacRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_roles(self) -> list[Role]:
        result = await self._session.execute(select(Role).order_by(Role.code))
        return list(result.scalars().all())

    async def list_permissions(self) -> list[Permission]:
        result = await self._session.execute(select(Permission).order_by(Permission.code))
        return list(result.scalars().all())

    async def get_role_by_code(self, code: str | RoleCode) -> Role | None:
        result = await self._session.execute(select(Role).where(Role.code == str(code)))
        return result.scalar_one_or_none()

    async def get_permission_by_code(self, code: str | PermissionCode) -> Permission | None:
        result = await self._session.execute(
            select(Permission).where(Permission.code == str(code))
        )
        return result.scalar_one_or_none()

    async def seed_defaults(self) -> None:
        """Idempotently create roles, permissions and role-permission links."""
        roles_by_code: dict[RoleCode, Role] = {}
        for code, name in ROLE_NAMES.items():
            role = await self.get_role_by_code(code)
            if role is None:
                role = Role(code=code.value, name=name)
                self._session.add(role)
                await self._session.flush()
            roles_by_code[code] = role

        perms_by_code: dict[PermissionCode, Permission] = {}
        for code, name in PERMISSION_NAMES.items():
            permission = await self.get_permission_by_code(code)
            if permission is None:
                permission = Permission(code=code.value, name=name)
                self._session.add(permission)
                await self._session.flush()
            perms_by_code[code] = permission

        for role_code, permission_codes in ROLE_PERMISSIONS.items():
            role = roles_by_code[role_code]
            linked = {
                row.permission_id
                for row in (
                    await self._session.execute(
                        select(RolePermission).where(RolePermission.role_id == role.id)
                    )
                )
                .scalars()
                .all()
            }
            for permission_code in permission_codes:
                permission = perms_by_code[permission_code]
                if permission.id not in linked:
                    self._session.add(
                        RolePermission(role_id=role.id, permission_id=permission.id)
                    )
        await self._session.flush()

    async def assign_roles(self, account_id: UUID, role_codes: list[str]) -> list[Role]:
        """Replace the account's role set with the given codes."""
        existing = await self.list_account_roles(account_id)
        existing_by_code = {role.code: role for role in existing}

        target: list[Role] = []
        for code in role_codes:
            role = existing_by_code.get(code)
            if role is None:
                role = await self.get_role_by_code(code)
            if role is None:
                raise RoleNotFoundError(f"unknown role code: {code}")
            target.append(role)

        target_codes = {role.code for role in target}
        for role in existing:
            if role.code not in target_codes:
                row = await self._session.scalar(
                    select(AccountRole).where(
                        AccountRole.account_id == account_id,
                        AccountRole.role_id == role.id,
                    )
                )
                if row is not None:
                    await self._session.delete(row)

        for role in target:
            if role.code not in existing_by_code:
                self._session.add(AccountRole(account_id=account_id, role_id=role.id))
        await self._session.flush()
        return target

    async def list_account_roles(self, account_id: UUID) -> list[Role]:
        result = await self._session.execute(
            select(Role)
            .join(AccountRole, AccountRole.role_id == Role.id)
            .where(AccountRole.account_id == account_id)
            .order_by(Role.code)
        )
        return list(result.scalars().all())

    async def account_permissions(self, account_id: UUID) -> set[PermissionCode]:
        result = await self._session.execute(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(AccountRole, AccountRole.role_id == Role.id)
            .where(AccountRole.account_id == account_id)
        )
        return {PermissionCode(code) for code in result.scalars().all()}