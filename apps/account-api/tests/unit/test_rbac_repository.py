from uuid import uuid4

import pytest
from app.domain.account import PermissionCode, RoleCode, RoleNotFoundError
from app.models.role import Permission, Role, RolePermission
from app.repositories.rbac import ROLE_PERMISSIONS, RbacRepository
from sqlalchemy import func, select


async def _seed(db_session) -> RbacRepository:
    repo = RbacRepository(db_session)
    await repo.seed_defaults()
    return repo


async def test_seed_defaults_is_idempotent(db_session):
    repo = await _seed(db_session)
    await repo.seed_defaults()
    await repo.seed_defaults()

    roles = await db_session.execute(select(func.count()).select_from(Role))
    permissions = await db_session.execute(select(func.count()).select_from(Permission))
    links = await db_session.execute(select(func.count()).select_from(RolePermission))

    assert roles.scalar_one() == len(RoleCode)
    assert permissions.scalar_one() == len(PermissionCode)
    assert links.scalar_one() == sum(len(perms) for perms in ROLE_PERMISSIONS.values())


async def test_account_permissions_join(db_session):
    repo = await _seed(db_session)
    account_id = uuid4()
    await repo.assign_roles(account_id, [RoleCode.CLIENT.value])

    permissions = await repo.account_permissions(account_id)
    assert permissions == ROLE_PERMISSIONS[RoleCode.CLIENT]
    assert PermissionCode.USER_MANAGE not in permissions


async def test_specialist_inherits_client_and_encounter_permissions(db_session):
    repo = await _seed(db_session)
    account_id = uuid4()
    await repo.assign_roles(account_id, [RoleCode.SPECIALIST.value])

    permissions = await repo.account_permissions(account_id)
    assert ROLE_PERMISSIONS[RoleCode.CLIENT] <= permissions
    assert {
        PermissionCode.ENCOUNTER_READ,
        PermissionCode.ENCOUNTER_CREATE,
        PermissionCode.ENCOUNTER_UPDATE,
        PermissionCode.MEDICAL_RECORD_WRITE,
        PermissionCode.ANALYTICS_READ,
    } <= permissions
    assert PermissionCode.USER_MANAGE not in permissions


async def test_system_admin_has_all_permissions(db_session):
    repo = await _seed(db_session)
    account_id = uuid4()
    await repo.assign_roles(account_id, [RoleCode.SYSTEM_ADMIN.value])

    permissions = await repo.account_permissions(account_id)
    assert permissions == set(PermissionCode)


async def test_assign_roles_replaces_full_set(db_session):
    repo = await _seed(db_session)
    account_id = uuid4()
    await repo.assign_roles(
        account_id, [RoleCode.CLIENT.value, RoleCode.SPECIALIST.value]
    )

    roles = await repo.assign_roles(account_id, [RoleCode.CLIENT.value])
    assert [role.code for role in roles] == [RoleCode.CLIENT.value]

    account_roles = await repo.list_account_roles(account_id)
    assert [role.code for role in account_roles] == [RoleCode.CLIENT.value]


async def test_assign_roles_unknown_code_raises(db_session):
    repo = await _seed(db_session)
    with pytest.raises(RoleNotFoundError):
        await repo.assign_roles(uuid4(), ["no_such_role"])


async def test_list_roles_and_permissions_ordered_by_code(db_session):
    repo = await _seed(db_session)
    roles = await repo.list_roles()
    permissions = await repo.list_permissions()

    assert [role.code for role in roles] == sorted(role.value for role in RoleCode)
    assert [perm.code for perm in permissions] == sorted(
        perm.value for perm in PermissionCode
    )