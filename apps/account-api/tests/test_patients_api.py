from uuid import UUID, uuid4

from app.domain.access import GrantStatus
from app.domain.account import RoleCode
from app.models.access_grant import PatientAccessGrant
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.person import Person
from app.repositories.rbac import RbacRepository
from sqlalchemy import func, select


def _identity() -> str:
    return f"patient_{uuid4().hex[:8]}@example.com"


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
    resp = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert resp.status_code == 200
    return UUID(resp.json()["id"])


async def _grant(db_factory, patient_id: UUID, account_id: UUID) -> None:
    async with db_factory() as session:
        rbac = RbacRepository(session)
        await rbac.seed_defaults()
        await rbac.assign_roles(account_id, [RoleCode.SPECIALIST.value])
        session.add(
            PatientAccessGrant(
                patient_id=patient_id, account_id=account_id, status=GrantStatus.ACTIVE
            )
        )
        await session.commit()


async def test_patients_routes_require_auth(app_client):
    resp = await app_client.get(f"/api/v1/patients/{uuid4()}")
    assert resp.status_code == 401


async def test_create_patient_and_read_me(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    headers = _auth(token)

    created = await app_client.post("/api/v1/patients", headers=headers)
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "active"
    assert body["person"]["first_name"] == ""

    me = await app_client.get("/api/v1/patients/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["id"] == body["id"]


async def test_create_patient_with_person_data(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    headers = _auth(token)

    resp = await app_client.post(
        "/api/v1/patients",
        json={"person": {"first_name": "Ivan", "last_name": "Petrov", "sex": "male"}},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["person"]["first_name"] == "Ivan"
    assert resp.json()["person"]["last_name"] == "Petrov"


async def test_create_patient_conflict(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    headers = _auth(token)

    assert (await app_client.post("/api/v1/patients", headers=headers)).status_code == 201
    resp = await app_client.post("/api/v1/patients", headers=headers)
    assert resp.status_code == 409


async def test_get_me_auto_creates(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    headers = _auth(token)

    resp = await app_client.get("/api/v1/patients/me", headers=headers)
    assert resp.status_code == 200
    patient_id = resp.json()["id"]

    async with db_factory() as session:
        patients = await session.scalar(
            select(func.count()).select_from(Patient).where(Patient.id == UUID(patient_id))
        )
        records = await session.scalar(
            select(func.count()).select_from(MedicalRecord)
        )
        persons = await session.scalar(select(func.count()).select_from(Person))
    assert patients == 1
    assert records == 1
    assert persons == 1


async def test_patch_me_updates_person(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    headers = _auth(token)

    patched = await app_client.patch(
        "/api/v1/patients/me",
        json={"first_name": "Olga", "date_of_birth": "1992-03-03"},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["person"]["first_name"] == "Olga"

    me = await app_client.get("/api/v1/patients/me", headers=headers)
    assert me.json()["person"]["first_name"] == "Olga"
    assert me.json()["person"]["date_of_birth"] == "1992-03-03"


async def test_get_patient_owner_ok(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    headers = _auth(token)

    created = await app_client.post("/api/v1/patients", headers=headers)
    patient_id = created.json()["id"]

    resp = await app_client.get(f"/api/v1/patients/{patient_id}", headers=headers)
    assert resp.status_code == 200


async def test_get_patient_stranger_404(app_client, fake_redis):
    owner = await _register(app_client, fake_redis, _identity())
    stranger = await _register(app_client, fake_redis, _identity())

    created = await app_client.post(
        "/api/v1/patients", headers=_auth(owner)
    )
    patient_id = created.json()["id"]

    resp = await app_client.get(
        f"/api/v1/patients/{patient_id}", headers=_auth(stranger)
    )
    assert resp.status_code == 404


async def test_get_patient_specialist_with_grant_ok(app_client, fake_redis, db_factory):
    owner = await _register(app_client, fake_redis, _identity())
    specialist = await _register(app_client, fake_redis, _identity())

    created = await app_client.post("/api/v1/patients", headers=_auth(owner))
    patient_id = UUID(created.json()["id"])
    specialist_id = await _account_id(app_client, specialist)
    await _grant(db_factory, patient_id, specialist_id)

    resp = await app_client.get(
        f"/api/v1/patients/{patient_id}", headers=_auth(specialist)
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == str(patient_id)


async def test_get_patient_specialist_without_grant_404(
    app_client, fake_redis, db_factory
):
    owner = await _register(app_client, fake_redis, _identity())
    specialist = await _register(app_client, fake_redis, _identity())

    created = await app_client.post("/api/v1/patients", headers=_auth(owner))
    patient_id = created.json()["id"]

    resp = await app_client.get(
        f"/api/v1/patients/{patient_id}", headers=_auth(specialist)
    )
    assert resp.status_code == 404


async def test_get_unknown_patient_404(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    resp = await app_client.get(f"/api/v1/patients/{uuid4()}", headers=_auth(token))
    assert resp.status_code == 404