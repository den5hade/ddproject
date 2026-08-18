from uuid import UUID, uuid4

from app.domain.account import PermissionCode, RoleCode
from app.services.rbac import RbacService


def _identity() -> str:
    return f"rbac_{uuid4().hex[:8]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, fake_redis, identity: str) -> str:
    resp = await client.post("/api/v1/auth/request-otp", json={"identity": identity})
    assert resp.status_code == 202
    code = await fake_redis.get(f"otp:code:{identity}")
    assert code is not None
    resp = await client.post(
        "/api/v1/auth/verify", json={"identity": identity, "code": code}
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _account_id(client, token: str) -> UUID:
    resp = await client.get(
        "/api/v1/auth/me", headers=_auth(token)
    )
    assert resp.status_code == 200
    return UUID(resp.json()["id"])


async def _grant_roles(db_factory, account_id: UUID, *codes: RoleCode) -> None:
    async with db_factory() as session:
        service = RbacService(session)
        await service.seed()
        await service.assign_roles(account_id, [code.value for code in codes])


async def _register_admin(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    await _grant_roles(db_factory, account_id, RoleCode.SYSTEM_ADMIN)
    return token, account_id


async def test_admin_routes_require_auth(app_client):
    resp = await app_client.get(f"/api/v1/admin/accounts/{uuid4()}/roles")
    assert resp.status_code == 401


async def test_admin_routes_forbid_non_admin(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    await _grant_roles(db_factory, account_id, RoleCode.CLIENT)

    resp = await app_client.get(
        f"/api/v1/admin/accounts/{account_id}/roles", headers=_auth(token)
    )
    assert resp.status_code == 403


async def test_seed_idempotent(app_client, fake_redis, db_factory):
    token, _account_id = await _register_admin(app_client, fake_redis, db_factory)
    headers = _auth(token)

    resp = await app_client.post("/api/v1/admin/rbac/seed", headers=headers)
    assert resp.status_code == 204
    resp = await app_client.post("/api/v1/admin/rbac/seed", headers=headers)
    assert resp.status_code == 204


async def test_assign_and_list_roles(app_client, fake_redis, db_factory):
    token, _admin_id = await _register_admin(app_client, fake_redis, db_factory)
    headers = _auth(token)

    target = await _register(app_client, fake_redis, _identity())
    target_id = await _account_id(app_client, target)

    resp = await app_client.post(
        f"/api/v1/admin/accounts/{target_id}/roles",
        json={
            "role_codes": [RoleCode.CLIENT.value, RoleCode.SPECIALIST.value]
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert {role["code"] for role in resp.json()["roles"]} == {
        RoleCode.CLIENT.value,
        RoleCode.SPECIALIST.value,
    }

    resp = await app_client.post(
        f"/api/v1/admin/accounts/{target_id}/roles",
        json={"role_codes": [RoleCode.CLIENT.value]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert [role["code"] for role in resp.json()["roles"]] == [RoleCode.CLIENT.value]

    resp = await app_client.get(
        f"/api/v1/admin/accounts/{target_id}/roles", headers=headers
    )
    assert resp.status_code == 200
    assert [role["code"] for role in resp.json()["roles"]] == [RoleCode.CLIENT.value]


async def test_assign_unknown_role_returns_404(app_client, fake_redis, db_factory):
    token, _admin_id = await _register_admin(app_client, fake_redis, db_factory)
    headers = _auth(token)
    target_id = await _account_id(
        app_client, await _register(app_client, fake_redis, _identity())
    )

    resp = await app_client.post(
        f"/api/v1/admin/accounts/{target_id}/roles",
        json={"role_codes": ["no_such_role"]},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_list_permissions(app_client, fake_redis, db_factory):
    token, admin_id = await _register_admin(app_client, fake_redis, db_factory)

    resp = await app_client.get(
        f"/api/v1/admin/accounts/{admin_id}/permissions", headers=_auth(token)
    )
    assert resp.status_code == 200
    codes = {permission["code"] for permission in resp.json()}
    assert PermissionCode.USER_MANAGE.value in codes
    assert codes == {permission.value for permission in PermissionCode}