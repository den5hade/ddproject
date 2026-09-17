from uuid import UUID, uuid4

from app.domain.medical import MembershipStatus, OrganizationType
from app.domain.organization import OrganizationMembershipRole
from app.models.organization import Organization, OrganizationMembership


def _identity() -> str:
    return f"schema_{uuid4().hex[:8]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _definition() -> dict:
    return {"type": "object", "properties": {"hemoglobin": {"type": "number"}}}


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
    role: OrganizationMembershipRole = OrganizationMembershipRole.OWNER,
) -> None:
    async with db_factory() as session:
        session.add(
            OrganizationMembership(
                organization_id=organization_id,
                account_id=account_id,
                role=role,
                status=MembershipStatus.ACTIVE,
            )
        )
        await session.commit()


async def _org(db_factory, *, name: str = "City Clinic") -> Organization:
    async with db_factory() as session:
        org = Organization(name=name, type=OrganizationType.CLINIC)
        session.add(org)
        await session.commit()
        return org


async def _owner_account(
    app_client, fake_redis, db_factory, *, name: str = "City Clinic"
) -> tuple[str, UUID, UUID]:
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org = await _org(db_factory, name=name)
    await _membership(db_factory, org.id, account_id)
    return token, account_id, org.id


async def test_schemas_require_auth(app_client):
    resp = await app_client.get("/api/v1/organizations/me/schemas")
    assert resp.status_code == 401


async def test_member_role_cannot_manage_schemas(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org = await _org(db_factory)
    await _membership(db_factory, org.id, account_id, role=OrganizationMembershipRole.MEMBER)
    created = await app_client.post(
        "/api/v1/organizations/me/schemas",
        headers=_auth(token),
        json={"name": "lab_blood", "schema_definition": _definition()},
    )
    assert created.status_code == 403
    listed = await app_client.get(
        "/api/v1/organizations/me/schemas", headers=_auth(token)
    )
    assert listed.status_code == 403
    published = await app_client.post(
        f"/api/v1/organizations/me/schemas/{uuid4()}/publish",
        headers=_auth(token),
    )
    assert published.status_code == 403


async def test_list_empty_schemas(app_client, fake_redis, db_factory):
    token, _, _ = await _owner_account(app_client, fake_redis, db_factory)
    resp = await app_client.get("/api/v1/organizations/me/schemas", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_schema_201_shape(app_client, fake_redis, db_factory):
    token, _, org_id = await _owner_account(app_client, fake_redis, db_factory)
    resp = await app_client.post(
        "/api/v1/organizations/me/schemas",
        headers=_auth(token),
        json={
            "name": "lab_blood",
            "description": "general blood panel",
            "document_type": "lab_result",
            "schema_definition": _definition(),
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["organization_id"] == str(org_id)
    assert body["name"] == "lab_blood"
    assert body["document_type"] == "lab_result"
    assert body["version"] == 1
    assert body["status"] == "draft"
    assert body["published_at"] is None


async def test_create_duplicate_draft_409(app_client, fake_redis, db_factory):
    token, _, _ = await _owner_account(app_client, fake_redis, db_factory)
    payload = {"name": "lab_blood", "schema_definition": _definition()}
    first = await app_client.post(
        "/api/v1/organizations/me/schemas", headers=_auth(token), json=payload
    )
    assert first.status_code == 201
    dup = await app_client.post(
        "/api/v1/organizations/me/schemas", headers=_auth(token), json=payload
    )
    assert dup.status_code == 409


async def test_create_invalid_schema_definition_422(app_client, fake_redis, db_factory):
    token, _, _ = await _owner_account(app_client, fake_redis, db_factory)
    resp = await app_client.post(
        "/api/v1/organizations/me/schemas",
        headers=_auth(token),
        json={"name": "bad", "schema_definition": ["not", "an", "object"]},
    )
    assert resp.status_code == 422


async def test_update_draft_and_publish_flow(app_client, fake_redis, db_factory):
    token, _, _ = await _owner_account(app_client, fake_redis, db_factory)
    created = await app_client.post(
        "/api/v1/organizations/me/schemas",
        headers=_auth(token),
        json={"name": "lab_blood", "schema_definition": _definition()},
    )
    assert created.status_code == 201
    schema_id = created.json()["id"]

    updated = await app_client.patch(
        f"/api/v1/organizations/me/schemas/{schema_id}",
        headers=_auth(token),
        json={"description": "full blood count"},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "full blood count"

    published = await app_client.post(
        f"/api/v1/organizations/me/schemas/{schema_id}/publish",
        headers=_auth(token),
    )
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["published_at"] is not None


async def test_publish_twice_409(app_client, fake_redis, db_factory):
    token, _, _ = await _owner_account(app_client, fake_redis, db_factory)
    created = await app_client.post(
        "/api/v1/organizations/me/schemas",
        headers=_auth(token),
        json={"name": "lab_blood", "schema_definition": _definition()},
    )
    schema_id = created.json()["id"]
    first = await app_client.post(
        f"/api/v1/organizations/me/schemas/{schema_id}/publish",
        headers=_auth(token),
    )
    assert first.status_code == 200
    again = await app_client.post(
        f"/api/v1/organizations/me/schemas/{schema_id}/publish",
        headers=_auth(token),
    )
    assert again.status_code == 409


async def test_update_published_schema_422(app_client, fake_redis, db_factory):
    token, _, _ = await _owner_account(app_client, fake_redis, db_factory)
    created = await app_client.post(
        "/api/v1/organizations/me/schemas",
        headers=_auth(token),
        json={"name": "lab_blood", "schema_definition": _definition()},
    )
    schema_id = created.json()["id"]
    await app_client.post(
        f"/api/v1/organizations/me/schemas/{schema_id}/publish",
        headers=_auth(token),
    )
    patched = await app_client.patch(
        f"/api/v1/organizations/me/schemas/{schema_id}",
        headers=_auth(token),
        json={"description": "editing after publish"},
    )
    assert patched.status_code == 422


async def test_version_increments_via_new_draft(app_client, fake_redis, db_factory):
    token, _, _ = await _owner_account(app_client, fake_redis, db_factory)
    v1 = await app_client.post(
        "/api/v1/organizations/me/schemas",
        headers=_auth(token),
        json={"name": "lab_blood", "schema_definition": _definition()},
    )
    assert v1.json()["version"] == 1
    await app_client.post(
        f"/api/v1/organizations/me/schemas/{v1.json()['id']}/publish",
        headers=_auth(token),
    )
    v2 = await app_client.post(
        "/api/v1/organizations/me/schemas",
        headers=_auth(token),
        json={"name": "lab_blood", "schema_definition": _definition()},
    )
    assert v2.status_code == 201
    assert v2.json()["version"] == 2
    listed = await app_client.get(
        "/api/v1/organizations/me/schemas", headers=_auth(token)
    )
    assert listed.status_code == 200
    versions = [s["version"] for s in listed.json()]
    assert versions == [1, 2]


async def test_update_missing_or_foreign_schema_404(app_client, fake_redis, db_factory):
    token, _, _ = await _owner_account(app_client, fake_redis, db_factory)
    missing = await app_client.patch(
        f"/api/v1/organizations/me/schemas/{uuid4()}",
        headers=_auth(token),
        json={"description": "nope"},
    )
    assert missing.status_code == 404
    missing_publish = await app_client.post(
        f"/api/v1/organizations/me/schemas/{uuid4()}/publish",
        headers=_auth(token),
    )
    assert missing_publish.status_code == 404


async def test_schemas_are_org_scoped(app_client, fake_redis, db_factory):
    token_a, _, _ = await _owner_account(app_client, fake_redis, db_factory)
    created = await app_client.post(
        "/api/v1/organizations/me/schemas",
        headers=_auth(token_a),
        json={"name": "lab_blood", "schema_definition": _definition()},
    )
    schema_id = created.json()["id"]

    org_b = await _org(db_factory, name="Other Clinic")
    token_b = await _register(app_client, fake_redis, _identity())
    account_b = await _account_id(app_client, token_b)
    await _membership(db_factory, org_b.id, account_b)
    foreign = await app_client.patch(
        f"/api/v1/organizations/me/schemas/{schema_id}",
        headers=_auth(token_b),
        json={"description": "not mine"},
    )
    assert foreign.status_code == 404


async def test_publish_requires_org_context_for_multi_membership(
    app_client, fake_redis, db_factory
):
    token, account_id, org_a = await _owner_account(
        app_client, fake_redis, db_factory, name="Clinic A"
    )
    org_b = await _org(db_factory, name="Clinic B")
    await _membership(db_factory, org_b.id, account_id)
    no_header = await app_client.post(
        "/api/v1/organizations/me/schemas",
        headers=_auth(token),
        json={"name": "lab_blood", "schema_definition": _definition()},
    )
    assert no_header.status_code == 400
    scoped = await app_client.post(
        "/api/v1/organizations/me/schemas",
        headers={**_auth(token), "X-Organization-Id": str(org_b.id)},
        json={"name": "lab_blood", "schema_definition": _definition()},
    )
    assert scoped.status_code == 201
    assert scoped.json()["organization_id"] == str(org_b.id)