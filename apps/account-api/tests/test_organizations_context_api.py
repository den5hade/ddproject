from uuid import UUID, uuid4

from app.domain.medical import MembershipStatus, OrganizationType
from app.domain.organization import OrganizationMembershipRole
from app.models.organization import Organization, OrganizationMembership
from sqlalchemy import select


def _identity() -> str:
    return f"ctx_{uuid4().hex[:8]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


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


async def _membership(
    db_factory,
    organization_id: UUID,
    account_id: UUID,
    *,
    role: OrganizationMembershipRole = OrganizationMembershipRole.MEMBER,
) -> UUID:
    async with db_factory() as session:
        membership = OrganizationMembership(
            organization_id=organization_id,
            account_id=account_id,
            role=role,
            status=MembershipStatus.ACTIVE,
        )
        session.add(membership)
        await session.commit()
        return membership.id


async def _org(db_factory, *, name: str = "City Clinic") -> Organization:
    async with db_factory() as session:
        org = Organization(name=name, type=OrganizationType.CLINIC)
        session.add(org)
        await session.commit()
        return org


async def _member_role_account(app_client, fake_redis, db_factory) -> tuple[str, UUID, UUID]:
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org = await _org(db_factory)
    await _membership(db_factory, org.id, account_id)
    return token, account_id, org.id


async def _owner_role_account(
    app_client, fake_redis, db_factory, *, name: str = "City Clinic"
) -> tuple[str, UUID, UUID]:
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org = await _org(db_factory, name=name)
    await _membership(
        db_factory, org.id, account_id, role=OrganizationMembershipRole.OWNER
    )
    return token, account_id, org.id


async def test_list_my_organizations_returns_active_memberships(
    app_client, fake_redis, db_factory
):
    token, account_id, _ = await _member_role_account(app_client, fake_redis, db_factory)
    org_b = await _org(db_factory, name="Second Clinic")
    await _membership(db_factory, org_b.id, account_id)
    resp = await app_client.get("/api/v1/organizations", headers=_auth(token))
    assert resp.status_code == 200
    names = {org["name"] for org in resp.json()}
    assert names == {"City Clinic", "Second Clinic"}


async def test_list_my_organizations_no_membership_403(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    resp = await app_client.get("/api/v1/organizations", headers=_auth(token))
    assert resp.status_code == 403


async def test_get_my_organization_by_id_scoped(app_client, fake_redis, db_factory):
    token, _, org_a = await _member_role_account(app_client, fake_redis, db_factory)
    org_b = await _org(db_factory, name="Other Clinic")
    resp = await app_client.get(
        f"/api/v1/organizations/{org_a}", headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == str(org_a)
    foreign = await app_client.get(
        f"/api/v1/organizations/{org_b.id}", headers=_auth(token)
    )
    assert foreign.status_code == 404


async def test_member_can_read_context_but_not_manage(app_client, fake_redis, db_factory):
    token, _, org_id = await _member_role_account(app_client, fake_redis, db_factory)
    list_resp = await app_client.get("/api/v1/organizations", headers=_auth(token))
    assert list_resp.status_code == 200
    get_resp = await app_client.get(
        f"/api/v1/organizations/{org_id}", headers=_auth(token)
    )
    assert get_resp.status_code == 200
    members = await app_client.get(
        f"/api/v1/organizations/{org_id}/members", headers=_auth(token)
    )
    assert members.status_code == 403
    me = await app_client.get("/api/v1/organizations/me", headers=_auth(token))
    assert me.status_code == 403
    create = await app_client.post(
        "/api/v1/organizations/me/branches",
        headers=_auth(token),
        json={"code": "br-1", "name": "Main"},
    )
    assert create.status_code == 403


async def test_owner_lists_organization_members(app_client, fake_redis, db_factory):
    token, _, org_id = await _owner_role_account(app_client, fake_redis, db_factory)
    second = await _register(app_client, fake_redis, _identity())
    second_id = await _account_id(app_client, second)
    await _membership(db_factory, org_id, second_id)
    resp = await app_client.get(
        f"/api/v1/organizations/{org_id}/members", headers=_auth(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    roles = {m["role"] for m in body}
    assert roles == {"owner", "member"}


async def test_members_list_foreign_org_404(app_client, fake_redis, db_factory):
    token, _, org_a = await _owner_role_account(app_client, fake_redis, db_factory)
    token_b = await _register(app_client, fake_redis, _identity())
    b_id = await _account_id(app_client, token_b)
    org_b = await _org(db_factory, name="Other Clinic")
    await _membership(db_factory, org_b.id, b_id, role=OrganizationMembershipRole.OWNER)
    resp = await app_client.get(
        f"/api/v1/organizations/{org_a}/members", headers=_auth(token_b)
    )
    assert resp.status_code == 404


async def test_ambiguous_org_context_requires_header(app_client, fake_redis, db_factory):
    token, account_id, org_a = await _owner_role_account(app_client, fake_redis, db_factory)
    org_b = await _org(db_factory, name="Second Clinic")
    await _membership(
        db_factory, org_b.id, account_id, role=OrganizationMembershipRole.OWNER
    )
    no_header = await app_client.get("/api/v1/organizations/me", headers=_auth(token))
    assert no_header.status_code == 400
    first = await app_client.get(
        "/api/v1/organizations/me",
        headers={**_auth(token), "X-Organization-Id": str(org_a)},
    )
    assert first.status_code == 200
    assert first.json()["id"] == str(org_a)
    second = await app_client.get(
        "/api/v1/organizations/me",
        headers={**_auth(token), "X-Organization-Id": str(org_b.id)},
    )
    assert second.status_code == 200
    assert second.json()["id"] == str(org_b.id)
    unknown = await app_client.get(
        "/api/v1/organizations/me",
        headers={**_auth(token), "X-Organization-Id": str(uuid4())},
    )
    assert unknown.status_code == 404


async def test_write_endpoints_require_explicit_org_for_multi_membership(
    app_client, fake_redis, db_factory
):
    token, account_id, _org_a = await _owner_role_account(app_client, fake_redis, db_factory)
    org_b = await _org(db_factory, name="Lab Plus")
    await _membership(
        db_factory, org_b.id, account_id, role=OrganizationMembershipRole.OWNER
    )
    no_header = await app_client.post(
        "/api/v1/organizations/me/branches",
        headers=_auth(token),
        json={"code": "br-1", "name": "Main"},
    )
    assert no_header.status_code == 400
    created = await app_client.post(
        "/api/v1/organizations/me/branches",
        headers={**_auth(token), "X-Organization-Id": str(org_b.id)},
        json={"code": "br-1", "name": "B Branch"},
    )
    assert created.status_code == 201
    assert created.json()["organization_id"] == str(org_b.id)
    scoped = await app_client.get(
        f"/api/v1/organizations/{org_b.id}/members",
        headers=_auth(token),
    )
    assert scoped.status_code == 200


async def test_single_membership_implicit_no_header(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org = await _org(db_factory, name="Solo Clinic")
    await _membership(db_factory, org.id, account_id, role=OrganizationMembershipRole.OWNER)
    resp = await app_client.get("/api/v1/organizations/me", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["id"] == str(org.id)


async def test_role_downgrade_owner_to_member_loses_manage_access(
    app_client, fake_redis, db_factory
):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org = await _org(db_factory, name="Downgrade Clinic")
    await _membership(db_factory, org.id, account_id, role=OrganizationMembershipRole.OWNER)
    me_ok = await app_client.get("/api/v1/organizations/me", headers=_auth(token))
    assert me_ok.status_code == 200
    async with db_factory() as session:
        membership = (
            await session.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == org.id,
                    OrganizationMembership.account_id == account_id,
                )
            )
        ).scalar_one()
        membership.role = OrganizationMembershipRole.MEMBER
        await session.commit()
    me_denied = await app_client.get("/api/v1/organizations/me", headers=_auth(token))
    assert me_denied.status_code == 403
    members = await app_client.get(
        f"/api/v1/organizations/{org.id}/members", headers=_auth(token)
    )
    assert members.status_code == 403
    read_ok = await app_client.get(
        f"/api/v1/organizations/{org.id}", headers=_auth(token)
    )
    assert read_ok.status_code == 200