from uuid import UUID, uuid4

from app.domain.account import RoleCode
from app.domain.medical import MembershipStatus, OrganizationType
from app.models.audit_log import AuditLog
from app.models.organization import (
    Organization,
    OrganizationApiKey,
    OrganizationBranch,
    OrganizationLicense,
    OrganizationMembership,
)
from app.repositories.rbac import RbacRepository
from sqlalchemy import select


def _identity() -> str:
    return f"org_{uuid4().hex[:8]}@example.com"


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


async def _assign_role(db_factory, account_id: UUID, roles: list[str]) -> None:
    async with db_factory() as session:
        rbac = RbacRepository(session)
        await rbac.seed_defaults()
        await rbac.assign_roles(account_id, roles)
        await session.commit()


async def _configure_org_admin(
    db_factory,
    account_id: UUID,
    *,
    name: str = "City Clinic",
    inn: str | None = None,
    ogrn: str | None = None,
) -> UUID:
    async with db_factory() as session:
        await _seed_admin(session, account_id)
        org = Organization(name=name, type=OrganizationType.CLINIC, inn=inn, ogrn=ogrn)
        session.add(org)
        await session.flush()
        session.add(
            OrganizationMembership(
                organization_id=org.id,
                account_id=account_id,
                status=MembershipStatus.ACTIVE,
            )
        )
        await session.commit()
        return org.id


async def _seed_admin(session, account_id: UUID) -> None:
    rbac = RbacRepository(session)
    await rbac.seed_defaults()
    await rbac.assign_roles(account_id, [RoleCode.ORGANIZATION_ADMIN.value])


async def _create_branch(db_factory, organization_id: UUID, code: str, name: str) -> UUID:
    async with db_factory() as session:
        branch = OrganizationBranch(
            organization_id=organization_id, code=code, name=name
        )
        session.add(branch)
        await session.commit()
        return branch.id


async def _create_license(
    db_factory,
    organization_id: UUID,
    license_number: str,
    license_type: str = "терапия",
) -> UUID:
    async with db_factory() as session:
        license = OrganizationLicense(
            organization_id=organization_id,
            license_number=license_number,
            license_type=license_type,
        )
        session.add(license)
        await session.commit()
        return license.id


async def _api_key(db_factory, organization_id: UUID, name: str = "demo") -> UUID:
    async with db_factory() as session:
        key = OrganizationApiKey(
            organization_id=organization_id,
            name=name,
            prefix="ddorg_tst_x",
            key_hash=f"hash-{uuid4().hex}",
        )
        session.add(key)
        await session.commit()
        return key.id


async def test_get_me_requires_auth(app_client, fake_redis):
    resp = await app_client.get("/api/v1/organizations/me")
    assert resp.status_code == 401


async def test_get_me_requires_admin_role(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    resp = await app_client.get("/api/v1/organizations/me", headers=_auth(token))
    assert resp.status_code == 403


async def test_get_me_admin_without_membership_403(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    await _assign_role(db_factory, account_id, [RoleCode.ORGANIZATION_ADMIN.value])
    resp = await app_client.get("/api/v1/organizations/me", headers=_auth(token))
    assert resp.status_code == 403


async def test_get_me_returns_organization(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org_id = await _configure_org_admin(db_factory, account_id, name="City Clinic")
    resp = await app_client.get("/api/v1/organizations/me", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert UUID(body["id"]) == org_id
    assert body["name"] == "City Clinic"
    assert body["type"] == "clinic"
    assert body["verification_status"] == "unverified"
    assert body["inn"] is None


async def test_patch_name_and_legal_data_sets_pending(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    await _configure_org_admin(db_factory, account_id)
    resp = await app_client.patch(
        "/api/v1/organizations/me",
        headers=_auth(token),
        json={"name": "Renamed", "inn": "7707083893", "legal_address": "ул. Ленина, 1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["inn"] == "7707083893"
    assert body["legal_address"] == "ул. Ленина, 1"
    assert body["verification_status"] == "pending"


async def test_patch_contact_only_keeps_unverified(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    await _configure_org_admin(db_factory, account_id)
    resp = await app_client.patch(
        "/api/v1/organizations/me",
        headers=_auth(token),
        json={"website": "https://clinic.example"},
    )
    assert resp.status_code == 200
    assert resp.json()["website"] == "https://clinic.example"
    assert resp.json()["verification_status"] == "unverified"


async def test_patch_invalid_inn_checksum_422(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    await _configure_org_admin(db_factory, account_id)
    resp = await app_client.patch(
        "/api/v1/organizations/me", headers=_auth(token), json={"inn": "7707083894"}
    )
    assert resp.status_code == 422


async def test_patch_invalid_ogrn_422(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    await _configure_org_admin(db_factory, account_id)
    resp = await app_client.patch(
        "/api/v1/organizations/me", headers=_auth(token), json={"ogrn": "1027700132194"}
    )
    assert resp.status_code == 422


async def test_patch_bad_length_inn_422(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    await _configure_org_admin(db_factory, account_id)
    resp = await app_client.patch(
        "/api/v1/organizations/me", headers=_auth(token), json={"inn": "770708389"}
    )
    assert resp.status_code == 422


async def test_patch_empty_body_422(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    await _configure_org_admin(db_factory, account_id)
    resp = await app_client.patch("/api/v1/organizations/me", headers=_auth(token), json={})
    assert resp.status_code == 422


async def test_patch_duplicate_inn_409(app_client, fake_redis, db_factory):
    token_a = await _register(app_client, fake_redis, _identity())
    a_id = await _account_id(app_client, token_a)
    await _configure_org_admin(db_factory, a_id, inn="7707083893")

    token_b = await _register(app_client, fake_redis, _identity())
    b_id = await _account_id(app_client, token_b)
    await _configure_org_admin(db_factory, b_id)
    resp = await app_client.patch(
        "/api/v1/organizations/me", headers=_auth(token_b), json={"inn": "7707083893"}
    )
    assert resp.status_code == 409


async def test_patch_duplicate_ogrn_409(app_client, fake_redis, db_factory):
    token_a = await _register(app_client, fake_redis, _identity())
    a_id = await _account_id(app_client, token_a)
    await _configure_org_admin(db_factory, a_id, ogrn="1027700132195")

    token_b = await _register(app_client, fake_redis, _identity())
    b_id = await _account_id(app_client, token_b)
    await _configure_org_admin(db_factory, b_id)
    resp = await app_client.patch(
        "/api/v1/organizations/me", headers=_auth(token_b), json={"ogrn": "1027700132195"}
    )
    assert resp.status_code == 409


async def test_patch_requires_admin(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    resp = await app_client.patch(
        "/api/v1/organizations/me", headers=_auth(token), json={"name": "x"}
    )
    assert resp.status_code == 403


async def test_patch_writes_audit_log(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org_id = await _configure_org_admin(db_factory, account_id)
    resp = await app_client.patch(
        "/api/v1/organizations/me",
        headers=_auth(token),
        json={"website": "https://x.example"},
    )
    assert resp.status_code == 200
    async with db_factory() as session:
        rows = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "ORGANIZATION_UPDATED")
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].action.value == "ORGANIZATION_UPDATED"
    assert rows[0].resource_id == org_id
    assert rows[0].metadata_["fields"] == ["website"]


async def test_branches_require_auth(app_client, fake_redis):
    resp = await app_client.get("/api/v1/organizations/me/branches")
    assert resp.status_code == 401


async def test_branches_require_admin(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    resp = await app_client.get("/api/v1/organizations/me/branches", headers=_auth(token))
    assert resp.status_code == 403


async def test_create_branch(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    await _configure_org_admin(db_factory, account_id)
    resp = await app_client.post(
        "/api/v1/organizations/me/branches",
        headers=_auth(token),
        json={"code": "br-1", "name": "Main Branch", "address": "ул. Кирова, 5"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["code"] == "br-1"
    assert body["name"] == "Main Branch"
    assert body["address"] == "ул. Кирова, 5"
    assert body["phone"] is None
    assert body["status"] == "active"


async def test_create_branch_invalid_code_422(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    await _configure_org_admin(db_factory, account_id)
    resp = await app_client.post(
        "/api/v1/organizations/me/branches",
        headers=_auth(token),
        json={"code": "bad code", "name": "X"},
    )
    assert resp.status_code == 422


async def test_create_duplicate_branch_code_409(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org_id = await _configure_org_admin(db_factory, account_id)
    await _create_branch(db_factory, org_id, "br-1", "Main")
    resp = await app_client.post(
        "/api/v1/organizations/me/branches",
        headers=_auth(token),
        json={"code": "br-1", "name": "Dup"},
    )
    assert resp.status_code == 409


async def test_list_branches_scoped_to_my_org(app_client, fake_redis, db_factory):
    token_a = await _register(app_client, fake_redis, _identity())
    a_id = await _account_id(app_client, token_a)
    org_a = await _configure_org_admin(db_factory, a_id)
    await _create_branch(db_factory, org_a, "br-a1", "A One")
    await _create_branch(db_factory, org_a, "br-a2", "A Two")

    token_b = await _register(app_client, fake_redis, _identity())
    b_id = await _account_id(app_client, token_b)
    org_b = await _configure_org_admin(db_factory, b_id, name="Other Clinic")
    await _create_branch(db_factory, org_b, "br-b1", "B One")

    resp = await app_client.get("/api/v1/organizations/me/branches", headers=_auth(token_a))
    assert resp.status_code == 200
    codes = [branch["code"] for branch in resp.json()]
    assert codes == ["br-a1", "br-a2"]


async def test_get_branch_other_org_404(app_client, fake_redis, db_factory):
    token_a = await _register(app_client, fake_redis, _identity())
    a_id = await _account_id(app_client, token_a)
    org_a = await _configure_org_admin(db_factory, a_id)
    branch_id = await _create_branch(db_factory, org_a, "br-1", "Main")

    token_b = await _register(app_client, fake_redis, _identity())
    b_id = await _account_id(app_client, token_b)
    await _configure_org_admin(db_factory, b_id, name="Other Clinic")
    resp = await app_client.get(
        f"/api/v1/organizations/me/branches/{branch_id}", headers=_auth(token_b)
    )
    assert resp.status_code == 404


async def test_patch_branch(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org_id = await _configure_org_admin(db_factory, account_id)
    branch_id = await _create_branch(db_factory, org_id, "br-1", "Main")
    resp = await app_client.patch(
        f"/api/v1/organizations/me/branches/{branch_id}",
        headers=_auth(token),
        json={"name": "HQ", "phone": "+7 495 000-00-00"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "HQ"
    assert body["phone"] == "+7 495 000-00-00"
    assert body["code"] == "br-1"


async def test_patch_duplicate_branch_code_409(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org_id = await _configure_org_admin(db_factory, account_id)
    await _create_branch(db_factory, org_id, "br-1", "One")
    branch_id = await _create_branch(db_factory, org_id, "br-2", "Two")
    resp = await app_client.patch(
        f"/api/v1/organizations/me/branches/{branch_id}",
        headers=_auth(token),
        json={"code": "br-1"},
    )
    assert resp.status_code == 409


async def test_patch_other_org_404(app_client, fake_redis, db_factory):
    token_a = await _register(app_client, fake_redis, _identity())
    a_id = await _account_id(app_client, token_a)
    org_a = await _configure_org_admin(db_factory, a_id)
    branch_id = await _create_branch(db_factory, org_a, "br-1", "Main")

    token_b = await _register(app_client, fake_redis, _identity())
    b_id = await _account_id(app_client, token_b)
    await _configure_org_admin(db_factory, b_id, name="Other Clinic")
    resp = await app_client.patch(
        f"/api/v1/organizations/me/branches/{branch_id}",
        headers=_auth(token_b),
        json={"name": "Hijack"},
    )
    assert resp.status_code == 404


async def test_delete_branch_soft_deactivates(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org_id = await _configure_org_admin(db_factory, account_id)
    branch_id = await _create_branch(db_factory, org_id, "br-1", "Main")
    resp = await app_client.delete(
        f"/api/v1/organizations/me/branches/{branch_id}", headers=_auth(token)
    )
    assert resp.status_code == 204
    list_resp = await app_client.get(
        "/api/v1/organizations/me/branches", headers=_auth(token)
    )
    assert list_resp.status_code == 200
    bodies = list_resp.json()
    assert len(bodies) == 1
    assert bodies[0]["status"] == "inactive"
    assert bodies[0]["id"] == str(branch_id)


async def test_delete_other_org_404(app_client, fake_redis, db_factory):
    token_a = await _register(app_client, fake_redis, _identity())
    a_id = await _account_id(app_client, token_a)
    org_a = await _configure_org_admin(db_factory, a_id)
    branch_id = await _create_branch(db_factory, org_a, "br-1", "Main")

    token_b = await _register(app_client, fake_redis, _identity())
    b_id = await _account_id(app_client, token_b)
    await _configure_org_admin(db_factory, b_id, name="Other Clinic")
    resp = await app_client.delete(
        f"/api/v1/organizations/me/branches/{branch_id}", headers=_auth(token_b)
    )
    assert resp.status_code == 404


async def test_licenses_require_auth(app_client, fake_redis):
    resp = await app_client.get("/api/v1/organizations/me/licenses")
    assert resp.status_code == 401


async def test_licenses_require_admin(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    resp = await app_client.get("/api/v1/organizations/me/licenses", headers=_auth(token))
    assert resp.status_code == 403


async def test_create_license(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    await _configure_org_admin(db_factory, account_id)
    resp = await app_client.post(
        "/api/v1/organizations/me/licenses",
        headers=_auth(token),
        json={
            "license_number": "ЛО-77-01-000001",
            "license_type": "стоматология",
            "issued_at": "2026-01-10",
            "expires_at": "2031-01-10",
            "scope": "амбулаторно-поликлиническая",
            "issuer": "Росздравнадзор",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["license_number"] == "ЛО-77-01-000001"
    assert body["license_type"] == "стоматология"
    assert body["status"] == "active"
    assert body["issued_at"] == "2026-01-10"
    assert body["expires_at"] == "2031-01-10"
    assert body["scope"] == "амбулаторно-поликлиническая"
    assert body["issuer"] == "Росздравнадзор"


async def test_create_license_expires_before_issued_422(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    await _configure_org_admin(db_factory, account_id)
    resp = await app_client.post(
        "/api/v1/organizations/me/licenses",
        headers=_auth(token),
        json={
            "license_number": "ЛО-77-01-000002",
            "license_type": "x",
            "issued_at": "2031-01-10",
            "expires_at": "2026-01-10",
        },
    )
    assert resp.status_code == 422


async def test_create_duplicate_license_number_409(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org_id = await _configure_org_admin(db_factory, account_id)
    await _create_license(db_factory, org_id, "ЛО-77-01-000001")
    resp = await app_client.post(
        "/api/v1/organizations/me/licenses",
        headers=_auth(token),
        json={"license_number": "ЛО-77-01-000001", "license_type": "терапия"},
    )
    assert resp.status_code == 409


async def test_list_licenses_scoped_to_my_org(app_client, fake_redis, db_factory):
    token_a = await _register(app_client, fake_redis, _identity())
    a_id = await _account_id(app_client, token_a)
    org_a = await _configure_org_admin(db_factory, a_id)
    await _create_license(db_factory, org_a, "ЛО-77-01-000001")
    await _create_license(db_factory, org_a, "ЛО-77-01-000002")

    token_b = await _register(app_client, fake_redis, _identity())
    b_id = await _account_id(app_client, token_b)
    org_b = await _configure_org_admin(db_factory, b_id, name="Other Clinic")
    await _create_license(db_factory, org_b, "ЛО-77-01-000009")

    resp = await app_client.get("/api/v1/organizations/me/licenses", headers=_auth(token_a))
    assert resp.status_code == 200
    numbers = [license["license_number"] for license in resp.json()]
    assert numbers == ["ЛО-77-01-000001", "ЛО-77-01-000002"]


async def test_get_license_other_org_404(app_client, fake_redis, db_factory):
    token_a = await _register(app_client, fake_redis, _identity())
    a_id = await _account_id(app_client, token_a)
    org_a = await _configure_org_admin(db_factory, a_id)
    license_id = await _create_license(db_factory, org_a, "ЛО-77-01-000001")

    token_b = await _register(app_client, fake_redis, _identity())
    b_id = await _account_id(app_client, token_b)
    await _configure_org_admin(db_factory, b_id, name="Other Clinic")
    resp = await app_client.get(
        f"/api/v1/organizations/me/licenses/{license_id}", headers=_auth(token_b)
    )
    assert resp.status_code == 404


async def test_patch_license(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org_id = await _configure_org_admin(db_factory, account_id)
    license_id = await _create_license(db_factory, org_id, "ЛО-77-01-000001")
    resp = await app_client.patch(
        f"/api/v1/organizations/me/licenses/{license_id}",
        headers=_auth(token),
        json={"scope": "урология", "status": "suspended"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "урология"
    assert body["status"] == "suspended"
    assert body["license_number"] == "ЛО-77-01-000001"


async def test_patch_duplicate_license_number_409(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org_id = await _configure_org_admin(db_factory, account_id)
    await _create_license(db_factory, org_id, "ЛО-77-01-000001")
    license_id = await _create_license(db_factory, org_id, "ЛО-77-01-000002")
    resp = await app_client.patch(
        f"/api/v1/organizations/me/licenses/{license_id}",
        headers=_auth(token),
        json={"license_number": "ЛО-77-01-000001"},
    )
    assert resp.status_code == 409


async def test_patch_license_other_org_404(app_client, fake_redis, db_factory):
    token_a = await _register(app_client, fake_redis, _identity())
    a_id = await _account_id(app_client, token_a)
    org_a = await _configure_org_admin(db_factory, a_id)
    license_id = await _create_license(db_factory, org_a, "ЛО-77-01-000001")

    token_b = await _register(app_client, fake_redis, _identity())
    b_id = await _account_id(app_client, token_b)
    await _configure_org_admin(db_factory, b_id, name="Other Clinic")
    resp = await app_client.patch(
        f"/api/v1/organizations/me/licenses/{license_id}",
        headers=_auth(token_b),
        json={"scope": "x"},
    )
    assert resp.status_code == 404


async def test_delete_license_soft_revokes(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org_id = await _configure_org_admin(db_factory, account_id)
    license_id = await _create_license(db_factory, org_id, "ЛО-77-01-000001")
    resp = await app_client.delete(
        f"/api/v1/organizations/me/licenses/{license_id}", headers=_auth(token)
    )
    assert resp.status_code == 204
    list_resp = await app_client.get(
        "/api/v1/organizations/me/licenses", headers=_auth(token)
    )
    assert list_resp.status_code == 200
    bodies = list_resp.json()
    assert len(bodies) == 1
    assert bodies[0]["status"] == "revoked"
    assert bodies[0]["id"] == str(license_id)


async def test_delete_license_other_org_404(app_client, fake_redis, db_factory):
    token_a = await _register(app_client, fake_redis, _identity())
    a_id = await _account_id(app_client, token_a)
    org_a = await _configure_org_admin(db_factory, a_id)
    license_id = await _create_license(db_factory, org_a, "ЛО-77-01-000001")

    token_b = await _register(app_client, fake_redis, _identity())
    b_id = await _account_id(app_client, token_b)
    await _configure_org_admin(db_factory, b_id, name="Other Clinic")
    resp = await app_client.delete(
        f"/api/v1/organizations/me/licenses/{license_id}", headers=_auth(token_b)
    )
    assert resp.status_code == 404


async def test_api_keys_require_auth(app_client, fake_redis):
    resp = await app_client.get("/api/v1/organizations/me/api-keys")
    assert resp.status_code == 401


async def test_api_keys_require_admin(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    resp = await app_client.get("/api/v1/organizations/me/api-keys", headers=_auth(token))
    assert resp.status_code == 403


async def test_create_api_key_returns_raw_once(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    await _configure_org_admin(db_factory, account_id)
    resp = await app_client.post(
        "/api/v1/organizations/me/api-keys",
        headers=_auth(token),
        json={"name": "doc-upload", "scopes": ["organization.documents.upload"]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "doc-upload"
    assert body["status"] == "active"
    assert body["prefix"] == body["raw_key"][:12]
    assert body["raw_key"].startswith("ddorg_tst_")
    assert body["permissions"] == ["organization.documents.upload"]

    list_resp = await app_client.get(
        "/api/v1/organizations/me/api-keys", headers=_auth(token)
    )
    assert list_resp.status_code == 200
    listed = list_resp.json()
    assert len(listed) == 1
    assert "raw_key" not in listed[0]
    assert listed[0]["id"] == body["id"]


async def test_create_api_key_requires_scopes_422(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    await _configure_org_admin(db_factory, account_id)
    resp = await app_client.post(
        "/api/v1/organizations/me/api-keys",
        headers=_auth(token),
        json={"name": "no-scopes", "scopes": []},
    )
    assert resp.status_code == 422


async def test_list_api_keys_scoped_to_my_org(app_client, fake_redis, db_factory):
    token_a = await _register(app_client, fake_redis, _identity())
    a_id = await _account_id(app_client, token_a)
    org_a = await _configure_org_admin(db_factory, a_id)
    await _api_key(db_factory, org_a, name="a-one")
    await _api_key(db_factory, org_a, name="a-two")

    token_b = await _register(app_client, fake_redis, _identity())
    b_id = await _account_id(app_client, token_b)
    org_b = await _configure_org_admin(db_factory, b_id, name="Other Clinic")
    await _api_key(db_factory, org_b, name="b-one")

    resp = await app_client.get("/api/v1/organizations/me/api-keys", headers=_auth(token_a))
    assert resp.status_code == 200
    names = [key["name"] for key in resp.json()]
    assert names == ["a-one", "a-two"]


async def test_revoke_api_key(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org_id = await _configure_org_admin(db_factory, account_id)
    key_id = await _api_key(db_factory, org_id)
    resp = await app_client.delete(
        f"/api/v1/organizations/me/api-keys/{key_id}", headers=_auth(token)
    )
    assert resp.status_code == 204
    list_resp = await app_client.get(
        "/api/v1/organizations/me/api-keys", headers=_auth(token)
    )
    bodies = list_resp.json()
    assert len(bodies) == 1
    assert bodies[0]["status"] == "revoked"
    assert bodies[0]["revoked_at"] is not None


async def test_revoke_api_key_other_org_404(app_client, fake_redis, db_factory):
    token_a = await _register(app_client, fake_redis, _identity())
    a_id = await _account_id(app_client, token_a)
    org_a = await _configure_org_admin(db_factory, a_id)
    key_id = await _api_key(db_factory, org_a)

    token_b = await _register(app_client, fake_redis, _identity())
    b_id = await _account_id(app_client, token_b)
    await _configure_org_admin(db_factory, b_id, name="Other Clinic")
    resp = await app_client.delete(
        f"/api/v1/organizations/me/api-keys/{key_id}", headers=_auth(token_b)
    )
    assert resp.status_code == 404


async def test_rotate_api_key(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org_id = await _configure_org_admin(db_factory, account_id)
    old_id = await _api_key(db_factory, org_id, name="rotating")
    resp = await app_client.post(
        f"/api/v1/organizations/me/api-keys/{old_id}/rotate", headers=_auth(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] != str(old_id)
    assert body["name"] == "rotating"
    assert body["status"] == "active"
    assert body["raw_key"].startswith("ddorg_tst_")

    list_resp = await app_client.get(
        "/api/v1/organizations/me/api-keys", headers=_auth(token)
    )
    by_id = {key["id"]: key for key in list_resp.json()}
    assert by_id[str(old_id)]["status"] == "revoked"
    assert by_id[body["id"]]["status"] == "active"


async def test_rotate_api_key_other_org_404(app_client, fake_redis, db_factory):
    token_a = await _register(app_client, fake_redis, _identity())
    a_id = await _account_id(app_client, token_a)
    org_a = await _configure_org_admin(db_factory, a_id)
    key_id = await _api_key(db_factory, org_a)

    token_b = await _register(app_client, fake_redis, _identity())
    b_id = await _account_id(app_client, token_b)
    await _configure_org_admin(db_factory, b_id, name="Other Clinic")
    resp = await app_client.post(
        f"/api/v1/organizations/me/api-keys/{key_id}/rotate", headers=_auth(token_b)
    )
    assert resp.status_code == 404