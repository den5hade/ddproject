from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

from app.domain.medical import (
    DocumentStatus,
    MembershipStatus,
    OrganizationType,
)
from app.domain.organization import BatchStatus, OrganizationMembershipRole
from app.models.document import Document
from app.models.medical_record import MedicalRecord
from app.models.organization import (
    Organization,
    OrganizationApiRequest,
    OrganizationMembership,
    OrganizationUploadBatch,
)
from app.models.patient import Patient
from app.models.person import Person

DAY_KEYS = {
    "date",
    "requests",
    "successes",
    "errors",
    "success_rate",
    "error_rate",
    "documents",
    "documents_failed",
    "batches",
    "batch_items_failed",
}

TOP_KEYS = {
    "from",
    "to",
    "organization_id",
    "days",
    "total_requests",
    "total_successes",
    "total_errors",
    "overall_success_rate",
    "overall_error_rate",
    "total_documents",
    "total_documents_failed",
    "total_batches",
    "total_batch_items_failed",
}


def _identity() -> str:
    return f"usage_{uuid4().hex[:8]}@example.com"


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


async def _seed_request(
    db_factory, org_id: UUID, *, status_code: int, created_at: datetime
) -> None:
    async with db_factory() as session:
        session.add(
            OrganizationApiRequest(
                organization_id=org_id,
                request_id=uuid4().hex,
                method="POST",
                path="/integration/upload",
                status_code=status_code,
                duration_ms=12,
                created_at=created_at,
            )
        )
        await session.commit()


async def _seed_batch(db_factory, org_id: UUID, *, created_at: datetime) -> None:
    async with db_factory() as session:
        session.add(
            OrganizationUploadBatch(
                organization_id=org_id,
                status=BatchStatus.COMPLETED,
                total_count=20,
                accepted_count=15,
                failed_count=5,
                created_at=created_at,
            )
        )
        await session.commit()


async def _seed_document(
    db_factory, org_id: UUID, *, status: DocumentStatus, created_at: datetime
) -> None:
    async with db_factory() as session:
        person = Person()
        session.add(person)
        await session.flush()
        patient = Patient(person_id=person.id)
        session.add(patient)
        await session.flush()
        record = MedicalRecord(patient_id=patient.id)
        session.add(record)
        await session.flush()
        session.add(
            Document(
                medical_record_id=record.id,
                organization_id=org_id,
                status=status,
                created_at=created_at,
            )
        )
        await session.commit()


def _noon(days_ago: int) -> datetime:
    today = datetime.now(UTC).date()
    return datetime.combine(today - timedelta(days=days_ago), time(12, 0), tzinfo=UTC)


async def test_api_usage_requires_auth(app_client):
    resp = await app_client.get("/api/v1/organizations/me/api-usage")
    assert resp.status_code == 401


async def test_member_role_cannot_read_api_usage(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    org = await _org(db_factory)
    await _membership(db_factory, org.id, account_id, role=OrganizationMembershipRole.MEMBER)
    resp = await app_client.get("/api/v1/organizations/me/api-usage", headers=_auth(token))
    assert resp.status_code == 403


async def test_api_usage_empty_series_for_owner(app_client, fake_redis, db_factory):
    token, _, org_id = await _owner_account(app_client, fake_redis, db_factory)
    resp = await app_client.get("/api/v1/organizations/me/api-usage", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["organization_id"] == str(org_id)
    assert body["days"] == []
    assert body["total_requests"] == 0
    assert body["overall_success_rate"] == 0.0


async def test_api_usage_aggregates_and_stays_non_pii(app_client, fake_redis, db_factory):
    token, _, org_id = await _owner_account(app_client, fake_redis, db_factory)
    created = _noon(0)
    await _seed_request(db_factory, org_id, status_code=200, created_at=created)
    await _seed_request(db_factory, org_id, status_code=200, created_at=created)
    await _seed_request(db_factory, org_id, status_code=500, created_at=created)
    await _seed_batch(db_factory, org_id, created_at=created)
    await _seed_document(db_factory, org_id, status=DocumentStatus.UPLOADED, created_at=created)
    await _seed_document(db_factory, org_id, status=DocumentStatus.FAILED, created_at=created)

    today = datetime.now(UTC).date()
    resp = await app_client.get(
        "/api/v1/organizations/me/api-usage",
        headers=_auth(token),
        params={"from": today - timedelta(days=1), "to": today},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["from"] == str(today - timedelta(days=1))
    assert body["to"] == str(today)
    assert set(body) == TOP_KEYS
    assert len(body["days"]) == 1
    day = body["days"][0]
    assert set(day) == DAY_KEYS
    assert day["requests"] == 3
    assert (day["successes"], day["errors"]) == (2, 1)
    assert (day["success_rate"], day["error_rate"]) == (66.67, 33.33)
    assert (day["documents"], day["documents_failed"]) == (2, 1)
    assert (day["batches"], day["batch_items_failed"]) == (1, 5)
    assert body["total_requests"] == 3
    assert body["total_successes"] == 2
    assert body["total_errors"] == 1
    assert body["total_documents_failed"] == 1
    assert body["total_batch_items_failed"] == 5
    raw = resp.text
    for pii in ("patient", "email", "ip_address", "user_agent", "request_id", "external_id"):
        assert pii not in raw


async def test_api_usage_range_filters_days(app_client, fake_redis, db_factory):
    token, _, org_id = await _owner_account(app_client, fake_redis, db_factory)
    await _seed_request(db_factory, org_id, status_code=200, created_at=_noon(5))
    await _seed_request(db_factory, org_id, status_code=200, created_at=_noon(0))

    today = datetime.now(UTC).date()
    resp = await app_client.get(
        "/api/v1/organizations/me/api-usage",
        headers=_auth(token),
        params={"from": today, "to": today},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [d["date"] for d in body["days"]] == [str(today)]
    assert body["total_requests"] == 1


async def test_api_usage_reversed_range_422(app_client, fake_redis, db_factory):
    token, _, _ = await _owner_account(app_client, fake_redis, db_factory)
    today = datetime.now(UTC).date()
    resp = await app_client.get(
        "/api/v1/organizations/me/api-usage",
        headers=_auth(token),
        params={"from": today, "to": today - timedelta(days=1)},
    )
    assert resp.status_code == 422


async def test_api_usage_span_over_limit_422(app_client, fake_redis, db_factory):
    token, _, _ = await _owner_account(app_client, fake_redis, db_factory)
    today = datetime.now(UTC).date()
    resp = await app_client.get(
        "/api/v1/organizations/me/api-usage",
        headers=_auth(token),
        params={"from": today - timedelta(days=90), "to": today},
    )
    assert resp.status_code == 422


async def test_api_usage_is_org_scoped(app_client, fake_redis, db_factory):
    token_a, _, org_a = await _owner_account(app_client, fake_redis, db_factory)
    await _seed_request(db_factory, org_a, status_code=200, created_at=_noon(0))

    token_b, _, _ = await _owner_account(app_client, fake_redis, db_factory, name="Other Clinic")
    today = datetime.now(UTC).date()
    resp = await app_client.get(
        "/api/v1/organizations/me/api-usage",
        headers=_auth(token_b),
        params={"from": today - timedelta(days=1), "to": today},
    )
    assert resp.status_code == 200
    assert resp.json()["days"] == []
    assert resp.json()["total_requests"] == 0


async def test_api_usage_multi_membership_requires_header(app_client, fake_redis, db_factory):
    token, account_id, org_a = await _owner_account(
        app_client, fake_redis, db_factory, name="Clinic A"
    )
    org_b = await _org(db_factory, name="Clinic B")
    await _membership(db_factory, org_b.id, account_id)
    await _seed_request(db_factory, org_b.id, status_code=200, created_at=_noon(0))

    no_header = await app_client.get("/api/v1/organizations/me/api-usage", headers=_auth(token))
    assert no_header.status_code == 400

    resp = await app_client.get(
        "/api/v1/organizations/me/api-usage",
        headers={**_auth(token), "X-Organization-Id": str(org_b.id)},
    )
    assert resp.status_code == 200
    assert resp.json()["organization_id"] == str(org_b.id)
    assert resp.json()["total_requests"] == 1