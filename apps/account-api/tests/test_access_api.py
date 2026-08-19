from uuid import UUID, uuid4

from app.domain.access import AuditAction
from app.domain.account import RoleCode
from app.repositories.rbac import RbacRepository


def _identity() -> str:
    return f"acc_{uuid4().hex[:8]}@example.com"


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


async def _create_patient(client, token: str) -> UUID:
    resp = await client.post("/api/v1/patients", headers=_auth(token))
    assert resp.status_code == 201
    return UUID(resp.json()["id"])


async def _account_id(client, token: str) -> UUID:
    resp = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert resp.status_code == 200
    return UUID(resp.json()["id"])


async def _assign_role(db_factory, account_id: UUID, code: RoleCode) -> None:
    async with db_factory() as session:
        rbac = RbacRepository(session)
        await rbac.seed_defaults()
        await rbac.assign_roles(account_id, [code.value])
        await session.commit()


def _grant_payload(account_id: UUID) -> dict:
    return {
        "account_id": str(account_id),
        "can_view_documents": True,
        "access_reason": "treatment",
    }


async def test_access_grant_routes_require_auth(app_client):
    resp = await app_client.post(
        f"/api/v1/patients/{uuid4()}/access-grants", json=_grant_payload(uuid4())
    )
    assert resp.status_code == 401
    resp = await app_client.get(f"/api/v1/patients/{uuid4()}/access-grants")
    assert resp.status_code == 401
    resp = await app_client.patch(
        f"/api/v1/patients/{uuid4()}/access-grants/{uuid4()}", json={}
    )
    assert resp.status_code == 401
    resp = await app_client.delete(
        f"/api/v1/patients/{uuid4()}/access-grants/{uuid4()}"
    )
    assert resp.status_code == 401


async def test_owner_grant_flow(app_client, fake_redis):
    owner = await _register(app_client, fake_redis, _identity())
    specialist = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, owner)
    specialist_id = await _account_id(app_client, specialist)

    created = await app_client.post(
        f"/api/v1/patients/{patient_id}/access-grants",
        json=_grant_payload(specialist_id),
        headers=_auth(owner),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "active"
    assert body["can_view_documents"] is True
    assert body["access_reason"] == "treatment"
    grant_id = body["id"]

    listed = await app_client.get(
        f"/api/v1/patients/{patient_id}/access-grants", headers=_auth(owner)
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    patched = await app_client.patch(
        f"/api/v1/patients/{patient_id}/access-grants/{grant_id}",
        json={"can_upload_documents": True, "expires_at": None},
        headers=_auth(owner),
    )
    assert patched.status_code == 200
    assert patched.json()["can_upload_documents"] is True

    revoked = await app_client.delete(
        f"/api/v1/patients/{patient_id}/access-grants/{grant_id}",
        headers=_auth(owner),
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"


async def test_non_owner_cannot_manage_grants(app_client, fake_redis, db_factory):
    owner = await _register(app_client, fake_redis, _identity())
    stranger = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, owner)
    specialist_id = await _account_id(app_client, stranger)

    resp = await app_client.post(
        f"/api/v1/patients/{patient_id}/access-grants",
        json=_grant_payload(specialist_id),
        headers=_auth(stranger),
    )
    assert resp.status_code == 403

    resp = await app_client.get(
        f"/api/v1/patients/{patient_id}/access-grants", headers=_auth(stranger)
    )
    assert resp.status_code == 403


async def test_grant_not_found_404(app_client, fake_redis):
    owner = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, owner)

    resp = await app_client.delete(
        f"/api/v1/patients/{patient_id}/access-grants/{uuid4()}",
        headers=_auth(owner),
    )
    assert resp.status_code == 404


async def test_update_requires_field(app_client, fake_redis):
    owner = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, owner)

    resp = await app_client.patch(
        f"/api/v1/patients/{patient_id}/access-grants/{uuid4()}",
        json={},
        headers=_auth(owner),
    )
    assert resp.status_code == 422


async def test_audit_logs_require_admin(app_client, fake_redis, db_factory):
    user = await _register(app_client, fake_redis, _identity())
    resp = await app_client.get("/api/v1/audit-logs", headers=_auth(user))
    assert resp.status_code == 403


async def test_audit_logs_admin_reads_entries(app_client, fake_redis, db_factory):
    user = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, user)
    fetched = await app_client.get(
        f"/api/v1/patients/{patient_id}", headers=_auth(user)
    )
    assert fetched.status_code == 200

    admin = await _register(app_client, fake_redis, _identity())
    admin_id = await _account_id(app_client, admin)
    await _assign_role(db_factory, admin_id, RoleCode.SYSTEM_ADMIN)

    resp = await app_client.get("/api/v1/audit-logs", headers=_auth(admin))
    assert resp.status_code == 200
    actions = {entry["action"] for entry in resp.json()}
    assert AuditAction.LOGIN.value in actions
    assert AuditAction.VIEW_PATIENT.value in actions


async def test_audit_logs_filter_by_patient(app_client, fake_redis, db_factory):
    user = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, user)
    await app_client.get(f"/api/v1/patients/{patient_id}", headers=_auth(user))

    admin = await _register(app_client, fake_redis, _identity())
    admin_id = await _account_id(app_client, admin)
    await _assign_role(db_factory, admin_id, RoleCode.SYSTEM_ADMIN)

    resp = await app_client.get(
        f"/api/v1/audit-logs?patient_id={patient_id}", headers=_auth(admin)
    )
    assert resp.status_code == 200
    assert all(UUID(entry["patient_id"]) == patient_id for entry in resp.json())
