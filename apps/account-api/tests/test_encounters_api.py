from uuid import UUID, uuid4

from app.domain.access import GrantStatus
from app.models.access_grant import PatientAccessGrant


def _identity() -> str:
    return f"enc_{uuid4().hex[:8]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _encounter_payload() -> dict:
    return {"started_at": "2026-08-19T10:00:00Z", "reason": "checkup"}


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


async def _grant(
    db_factory,
    patient_id,
    account_id,
    *,
    create_encounters=False,
    edit_medical_data=False,
) -> None:
    async with db_factory() as session:
        session.add(
            PatientAccessGrant(
                patient_id=patient_id,
                account_id=account_id,
                status=GrantStatus.ACTIVE,
                can_create_encounters=create_encounters,
                can_edit_medical_data=edit_medical_data,
            )
        )
        await session.commit()


async def test_encounter_routes_require_auth(app_client):
    resp = await app_client.post(
        f"/api/v1/patients/{uuid4()}/encounters", json=_encounter_payload()
    )
    assert resp.status_code == 401
    resp = await app_client.get(f"/api/v1/patients/{uuid4()}/encounters")
    assert resp.status_code == 401
    resp = await app_client.get(f"/api/v1/encounters/{uuid4()}")
    assert resp.status_code == 401
    resp = await app_client.patch(f"/api/v1/encounters/{uuid4()}", json={})
    assert resp.status_code == 401
    resp = await app_client.get(f"/api/v1/encounters/{uuid4()}/documents")
    assert resp.status_code == 401


async def test_owner_encounter_flow(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    headers = _auth(token)
    patient_id = await _create_patient(app_client, token)

    created = await app_client.post(
        f"/api/v1/patients/{patient_id}/encounters",
        json=_encounter_payload(),
        headers=headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "scheduled"
    assert body["reason"] == "checkup"
    assert body["specialist_id"] is None
    encounter_id = body["id"]

    listed = await app_client.get(
        f"/api/v1/patients/{patient_id}/encounters", headers=headers
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == encounter_id

    fetched = await app_client.get(
        f"/api/v1/encounters/{encounter_id}", headers=headers
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == encounter_id

    patched = await app_client.patch(
        f"/api/v1/encounters/{encounter_id}",
        json={"status": "completed", "summary": "all fine"},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "completed"
    assert patched.json()["summary"] == "all fine"

    documents = await app_client.get(
        f"/api/v1/encounters/{encounter_id}/documents", headers=headers
    )
    assert documents.status_code == 200
    assert documents.json() == []


async def test_encounter_documents_linked(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    headers = _auth(token)
    patient_id = await _create_patient(app_client, token)

    created = await app_client.post(
        f"/api/v1/patients/{patient_id}/encounters",
        json=_encounter_payload(),
        headers=headers,
    )
    encounter_id = created.json()["id"]

    files = {"upload": ("scan.pdf", b"%PDF-1.4 test", "application/pdf")}
    resp = await app_client.post(
        f"/api/v1/patients/{patient_id}/documents",
        headers=headers,
        files=files,
        data={"encounter_id": encounter_id},
    )
    assert resp.status_code == 201
    assert resp.json()["encounter_id"] == encounter_id

    documents = await app_client.get(
        f"/api/v1/encounters/{encounter_id}/documents", headers=headers
    )
    assert documents.status_code == 200
    assert len(documents.json()) == 1


async def test_update_requires_at_least_one_field(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    headers = _auth(token)
    patient_id = await _create_patient(app_client, token)

    created = await app_client.post(
        f"/api/v1/patients/{patient_id}/encounters",
        json=_encounter_payload(),
        headers=headers,
    )
    encounter_id = created.json()["id"]

    resp = await app_client.patch(
        f"/api/v1/encounters/{encounter_id}", json={}, headers=headers
    )
    assert resp.status_code == 422


async def test_specialist_without_grant_denied(app_client, fake_redis):
    owner = await _register(app_client, fake_redis, _identity())
    specialist = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, owner)

    resp = await app_client.post(
        f"/api/v1/patients/{patient_id}/encounters",
        json=_encounter_payload(),
        headers=_auth(specialist),
    )
    assert resp.status_code == 403

    resp = await app_client.get(
        f"/api/v1/patients/{patient_id}/encounters", headers=_auth(specialist)
    )
    assert resp.status_code == 404

    created = await app_client.post(
        f"/api/v1/patients/{patient_id}/encounters",
        json=_encounter_payload(),
        headers=_auth(owner),
    )
    encounter_id = created.json()["id"]
    resp = await app_client.get(
        f"/api/v1/encounters/{encounter_id}", headers=_auth(specialist)
    )
    assert resp.status_code == 403


async def test_specialist_with_create_grant_ok(app_client, fake_redis, db_factory):
    owner = await _register(app_client, fake_redis, _identity())
    specialist = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, owner)
    specialist_id = await _account_id(app_client, specialist)
    await _grant(db_factory, patient_id, specialist_id, create_encounters=True)

    resp = await app_client.post(
        f"/api/v1/patients/{patient_id}/encounters",
        json=_encounter_payload(),
        headers=_auth(specialist),
    )
    assert resp.status_code == 201


async def test_specialist_with_edit_grant_patch_ok(app_client, fake_redis, db_factory):
    owner = await _register(app_client, fake_redis, _identity())
    specialist = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, owner)
    specialist_id = await _account_id(app_client, specialist)
    await _grant(db_factory, patient_id, specialist_id, edit_medical_data=True)

    created = await app_client.post(
        f"/api/v1/patients/{patient_id}/encounters",
        json=_encounter_payload(),
        headers=_auth(owner),
    )
    encounter_id = created.json()["id"]

    resp = await app_client.patch(
        f"/api/v1/encounters/{encounter_id}",
        json={"status": "completed"},
        headers=_auth(specialist),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
