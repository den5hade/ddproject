from uuid import UUID, uuid4

from app.domain.account import RoleCode
from app.domain.medical import OrganizationStatus
from app.models.account import Account
from app.models.audit_log import AuditLog
from app.models.organization import Organization, OrganizationMembership
from app.repositories.rbac import RbacRepository
from sqlalchemy import select


def _identity() -> str:
    return f"sa_{uuid4().hex[:8]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _payload(
    name: str = "City Clinic",
    inn: str = "7707083893",
    ogrn: str = "1027700132195",
    email: str | None = None,
    role: str = "owner",
) -> dict:
    return {
        "organization": {
            "name": name,
            "type": "clinic",
            "inn": inn,
            "ogrn": ogrn,
            "legal_address": "ул. Ленина, 1",
        },
        "administrator": {
            "email": email or f"rep_{uuid4().hex[:8]}@example.com",
            "role": role,
        },
    }


async def _register(client, fake_redis, identity: str) -> str:
    resp = await client.post("/api/v1/auth/request-otp", json={"identity": identity})
    assert resp.status_code == 202
    code = await fake_redis.get(f"otp:code:{identity}")
    assert code is not None
    resp = await client.post("/api/v1/auth/verify", json={"identity": identity, "code": code})
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _account_id(client, token: str) -> UUID:
    resp = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert resp.status_code == 200
    return UUID(resp.json()["id"])


async def _system_admin(db_factory, client, fake_redis) -> tuple[str, UUID]:
    token = await _register(client, fake_redis, _identity())
    account_id = await _account_id(client, token)
    async with db_factory() as session:
        rbac = RbacRepository(session)
        await rbac.seed_defaults()
        await rbac.assign_roles(account_id, [RoleCode.SYSTEM_ADMIN.value])
        await session.commit()
    return token, account_id


async def test_admin_organizations_require_auth(app_client, fake_redis):
    resp = await app_client.get("/api/v1/admin/organizations")
    assert resp.status_code == 401
    resp = await app_client.post("/api/v1/admin/organizations", json=_payload())
    assert resp.status_code == 401
    resp = await app_client.get("/api/v1/admin/organizations/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 401


async def test_admin_organizations_require_system_admin_role(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    resp = await app_client.post(
        "/api/v1/admin/organizations", headers=_auth(token), json=_payload()
    )
    assert resp.status_code == 403


async def test_members_endpoints_require_system_admin_role(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    resp = await app_client.get("/api/v1/admin/organizations", headers=_auth(token))
    assert resp.status_code == 403


async def test_system_admin_creates_organization_with_owner_membership(
    app_client, fake_redis, db_factory
):
    token, admin_id = await _system_admin(db_factory, app_client, fake_redis)
    resp = await app_client.post(
        "/api/v1/admin/organizations", headers=_auth(token), json=_payload()
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "City Clinic"
    assert body["type"] == "clinic"
    assert body["inn"] == "7707083893"
    assert body["status"] == "active"
    assert body["verification_status"] == "pending"
    assert body["created_by_account_id"] == str(admin_id)

    async with db_factory() as session:
        org = await session.get(Organization, UUID(body["id"]))
        assert org is not None
        assert org.created_by_account_id == admin_id
        membership = (
            await session.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == org.id
                )
            )
        ).scalar_one()
        assert membership.role.value == "owner"
        assert membership.status.value == "active"
        accounts = (
            await session.execute(select(Account))
        ).scalars().all()
        assert len(accounts) == 2
        rep = next(acc for acc in accounts if acc.id == membership.account_id)
        assert rep.email is not None
        assert rep.email_normalized is not None
        roles = await RbacRepository(session).list_account_roles(rep.id)
        assert [role.code for role in roles] == []


async def test_system_admin_reuses_existing_account_by_email(
    app_client, fake_redis, db_factory
):
    token, _ = await _system_admin(db_factory, app_client, fake_redis)
    email = f"existing_{uuid4().hex[:8]}@example.com"
    async with db_factory() as session:
        account = Account()
        account.email = email
        account.email_normalized = email
        session.add(account)
        await session.commit()
    resp = await app_client.post(
        "/api/v1/admin/organizations",
        headers=_auth(token),
        json=_payload(email=email.upper()),
    )
    assert resp.status_code == 201
    async with db_factory() as session:
        accounts = (await session.execute(select(Account))).scalars().all()
        assert len(accounts) == 2
        matching = [acc for acc in accounts if acc.email_normalized == email]
        assert len(matching) == 1


async def test_duplicate_inn_409(app_client, fake_redis, db_factory):
    token, _ = await _system_admin(db_factory, app_client, fake_redis)
    first = await app_client.post(
        "/api/v1/admin/organizations", headers=_auth(token), json=_payload()
    )
    assert first.status_code == 201
    dup = await app_client.post(
        "/api/v1/admin/organizations",
        headers=_auth(token),
        json=_payload(inn="7707083893", ogrn="1027700132206"),
    )
    assert dup.status_code == 409


async def test_duplicate_ogrn_409(app_client, fake_redis, db_factory):
    token, _ = await _system_admin(db_factory, app_client, fake_redis)
    first = await app_client.post(
        "/api/v1/admin/organizations", headers=_auth(token), json=_payload()
    )
    assert first.status_code == 201
    dup = await app_client.post(
        "/api/v1/admin/organizations",
        headers=_auth(token),
        json=_payload(inn="500100732259", ogrn="1027700132195"),
    )
    assert dup.status_code == 409


async def test_list_organizations_returns_all(app_client, fake_redis, db_factory):
    token, _ = await _system_admin(db_factory, app_client, fake_redis)
    await app_client.post("/api/v1/admin/organizations", headers=_auth(token), json=_payload())
    await app_client.post(
        "/api/v1/admin/organizations",
        headers=_auth(token),
        json=_payload(name="Lab Plus", inn="500100732259", ogrn="1027700132206"),
    )
    resp = await app_client.get("/api/v1/admin/organizations", headers=_auth(token))
    assert resp.status_code == 200
    names = {org["name"] for org in resp.json()}
    assert names == {"City Clinic", "Lab Plus"}


async def test_admin_list_and_get_expose_ownership_anchor(
    app_client, fake_redis, db_factory
):
    token, admin_id = await _system_admin(db_factory, app_client, fake_redis)
    created = await app_client.post(
        "/api/v1/admin/organizations", headers=_auth(token), json=_payload()
    )
    org_id = created.json()["id"]

    listed = await app_client.get("/api/v1/admin/organizations", headers=_auth(token))
    assert listed.status_code == 200
    assert all(
        org["created_by_account_id"] == str(admin_id) for org in listed.json()
    )

    fetched = await app_client.get(
        f"/api/v1/admin/organizations/{org_id}", headers=_auth(token)
    )
    assert fetched.status_code == 200
    assert fetched.json()["created_by_account_id"] == str(admin_id)


async def test_get_organization_404(app_client, fake_redis, db_factory):
    token, _ = await _system_admin(db_factory, app_client, fake_redis)
    resp = await app_client.get(
        "/api/v1/admin/organizations/00000000-0000-0000-0000-000000000000",
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_attach_member_to_existing_organization(app_client, fake_redis, db_factory):
    token, _ = await _system_admin(db_factory, app_client, fake_redis)
    org_resp = await app_client.post(
        "/api/v1/admin/organizations", headers=_auth(token), json=_payload()
    )
    org_id = org_resp.json()["id"]
    second = await app_client.post(
        f"/api/v1/admin/organizations/{org_id}/members",
        headers=_auth(token),
        json={"email": f"second_{uuid4().hex[:8]}@example.com", "role": "admin"},
    )
    assert second.status_code == 201
    body = second.json()
    assert body["role"] == "admin"
    assert body["status"] == "active"

    members = await app_client.get(
        f"/api/v1/admin/organizations/{org_id}/members", headers=_auth(token)
    )
    assert members.status_code == 200
    assert len(members.json()) == 2


async def test_attach_duplicate_membership_409(app_client, fake_redis, db_factory):
    token, _ = await _system_admin(db_factory, app_client, fake_redis)
    email = f"rep_{uuid4().hex[:8]}@example.com"
    org_resp = await app_client.post(
        "/api/v1/admin/organizations", headers=_auth(token), json=_payload(email=email)
    )
    org_id = org_resp.json()["id"]
    dup = await app_client.post(
        f"/api/v1/admin/organizations/{org_id}/members",
        headers=_auth(token),
        json={"email": email, "role": "admin"},
    )
    assert dup.status_code == 409


async def test_attach_member_missing_org_404(app_client, fake_redis, db_factory):
    token, _ = await _system_admin(db_factory, app_client, fake_redis)
    resp = await app_client.post(
        "/api/v1/admin/organizations/00000000-0000-0000-0000-000000000000/members",
        headers=_auth(token),
        json={"email": f"rep_{uuid4().hex[:8]}@example.com", "role": "owner"},
    )
    assert resp.status_code == 404


async def test_attach_member_inactive_org_409(app_client, fake_redis, db_factory):
    token, _ = await _system_admin(db_factory, app_client, fake_redis)
    async with db_factory() as session:
        org = Organization(name="Cold Clinic", type="clinic")
        org.status = OrganizationStatus.INACTIVE
        session.add(org)
        await session.commit()
        org_id = org.id
    resp = await app_client.post(
        f"/api/v1/admin/organizations/{org_id}/members",
        headers=_auth(token),
        json={"email": f"rep_{uuid4().hex[:8]}@example.com", "role": "owner"},
    )
    assert resp.status_code == 409


async def test_same_email_across_orgs_allowed(app_client, fake_redis, db_factory):
    token, _ = await _system_admin(db_factory, app_client, fake_redis)
    email = f"multi_{uuid4().hex[:8]}@example.com"
    org_a = await app_client.post(
        "/api/v1/admin/organizations", headers=_auth(token), json=_payload(email=email)
    )
    org_b = await app_client.post(
        "/api/v1/admin/organizations",
        headers=_auth(token),
        json=_payload(name="Second", inn="500100732259", ogrn="1027700132206", email=email),
    )
    assert org_a.status_code == 201
    assert org_b.status_code == 201
    async with db_factory() as session:
        memberships = (
            await session.execute(select(OrganizationMembership))
        ).scalars().all()
        org_pairs = {(m.organization_id, m.account_id) for m in memberships}
        assert len(org_pairs) == 2


async def test_bad_identity_in_member_payload_422(app_client, fake_redis, db_factory):
    token, _ = await _system_admin(db_factory, app_client, fake_redis)
    payload = _payload(email="+79165554433")  # phone is not an email
    resp = await app_client.post(
        "/api/v1/admin/organizations", headers=_auth(token), json=payload
    )
    assert resp.status_code == 422


async def test_admin_onboarding_writes_audit_rows(app_client, fake_redis, db_factory):
    token, _ = await _system_admin(db_factory, app_client, fake_redis)
    resp = await app_client.post(
        "/api/v1/admin/organizations", headers=_auth(token), json=_payload()
    )
    assert resp.status_code == 201
    async with db_factory() as session:
        rows = (
            (await session.execute(select(AuditLog))).scalars().all()
        )
        actions = [row.action.value for row in rows]
    assert "ORGANIZATION_CREATED" in actions
    assert "ORGANIZATION_ADMIN_ADDED" in actions