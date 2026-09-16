from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.domain.api_key import hash_api_key, prefix_for_raw_key
from app.domain.medical import OrganizationStatus, OrganizationType
from app.domain.organization import (
    OrganizationApiKeyStatus,
    OrganizationVerificationStatus,
)
from app.models.audit_log import AuditLog
from app.models.organization import (
    Organization,
    OrganizationApiKey,
    OrganizationApiRequest,
)
from app.services.rate_limit import RATE_LIMIT_KEY_PREFIX
from sqlalchemy import select

VALID_SCOPE = ["organization.documents.upload"]


def _identity() -> str:
    return f"org_{uuid4().hex[:8]}@example.com"


def _raw_key() -> str:
    return f"ddorg_tst_{uuid4().hex}"


_PDF = b"%PDF-1.7\n" + b"x" * 512


def _pdf_upload(email: str = "anna@clinic.example", **overrides) -> dict:
    data = {"patient_email": email}
    data.update(overrides.get("data", {}))
    return {
        "files": {"upload": ("scan.pdf", _PDF, "application/pdf")},
        "data": data,
    }


async def _org_and_key(
    db_factory,
    *,
    org_status: OrganizationStatus = OrganizationStatus.ACTIVE,
    verification: OrganizationVerificationStatus = OrganizationVerificationStatus.VERIFIED,
    key_status: OrganizationApiKeyStatus = OrganizationApiKeyStatus.ACTIVE,
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
    name: str = "City Clinic",
):
    raw_key = _raw_key()
    async with db_factory() as session:
        org = Organization(name=name, type=OrganizationType.CLINIC, status=org_status)
        org.verification_status = verification
        session.add(org)
        await session.flush()
        key = OrganizationApiKey(
            organization_id=org.id,
            name="demo",
            prefix=prefix_for_raw_key(raw_key),
            key_hash=hash_api_key(raw_key),
            permissions=scopes if scopes is not None else VALID_SCOPE,
            status=key_status,
            expires_at=expires_at,
        )
        session.add(key)
        await session.commit()
        return org.id, key.id, raw_key


async def _usage_request_id(
    db_factory, request_id: str
) -> OrganizationApiRequest | None:
    async with db_factory() as session:
        result = await session.execute(
            select(OrganizationApiRequest).where(
                OrganizationApiRequest.request_id == request_id
            )
        )
        return result.scalar_one_or_none()


async def test_integration_requires_bearer_token(app_client, db_factory):
    resp = await app_client.post("/api/v1/integration/documents")
    assert resp.status_code == 401


async def test_integration_invalid_key_401(app_client, db_factory):
    await _org_and_key(db_factory)
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers={"Authorization": f"Bearer {_raw_key()}"},
    )
    assert resp.status_code == 401


async def test_integration_revoked_key_401(app_client, db_factory):
    await _org_and_key(
        db_factory, key_status=OrganizationApiKeyStatus.REVOKED
    )
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers={"Authorization": f"Bearer {_raw_key()}"},
    )
    assert resp.status_code == 401


async def test_integration_expired_key_401(app_client, db_factory):
    _, _, raw = await _org_and_key(
        db_factory, expires_at=datetime.now(UTC) - timedelta(minutes=5)
    )
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert resp.status_code == 401


async def test_integration_inactive_org_403(app_client, db_factory):
    _, _, raw = await _org_and_key(
        db_factory, org_status=OrganizationStatus.INACTIVE
    )
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert resp.status_code == 403


async def test_integration_rejected_verification_403(app_client, db_factory):
    _, _, raw = await _org_and_key(
        db_factory, verification=OrganizationVerificationStatus.REJECTED
    )
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert resp.status_code == 403


async def test_integration_unverified_and_pending_orgs_pass(
    app_client, db_factory
):
    for verification in (
        OrganizationVerificationStatus.UNVERIFIED,
        OrganizationVerificationStatus.PENDING,
    ):
        _, _, raw = await _org_and_key(db_factory, verification=verification)
        resp = await app_client.post(
            "/api/v1/integration/documents",
            headers={"Authorization": f"Bearer {raw}"},
            **_pdf_upload(email=f"{uuid4().hex}@clinic.example"),
        )
        assert resp.status_code == 201


async def test_integration_missing_scope_403(app_client, db_factory):
    _, _, raw = await _org_and_key(db_factory, scopes=["organization.jobs.read"])
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert resp.status_code == 403


async def test_integration_rate_limit_429(app_client, db_factory, fake_redis):
    _, key_id, raw = await _org_and_key(db_factory)
    minute = int(datetime.now(UTC).timestamp()) // 60
    await fake_redis.set(
        f"{RATE_LIMIT_KEY_PREFIX}:{key_id}:{minute}",
        str(121),
    )
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert resp.status_code == 429


async def test_integration_happy_path_201_and_request_logged(
    app_client, db_factory
):
    _, key_id, raw = await _org_and_key(db_factory)
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers={
            "Authorization": f"Bearer {raw}",
            "X-Request-Id": "req-1234",
        },
        **_pdf_upload(),
    )
    assert resp.status_code == 201
    assert resp.headers.get("x-request-id") == "req-1234"

    async with db_factory() as session:
        result = await session.execute(
            select(OrganizationApiRequest).where(
                OrganizationApiRequest.request_id == "req-1234"
            )
        )
        row = result.scalar_one_or_none()
    assert row is not None
    assert row.organization_id is not None
    assert row.api_key_id == key_id
    assert row.method == "POST"
    assert row.path == "/api/v1/integration/documents"
    assert row.status_code == 201
    assert row.error_code is None
    assert row.duration_ms >= 0


async def test_integration_failed_auth_still_recorded(app_client, db_factory):
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers={
            "Authorization": f"Bearer {_raw_key()}",
            "X-Request-Id": "req-fail-1",
        },
    )
    assert resp.status_code == 401
    row = await _usage_request_id(db_factory, "req-fail-1")
    assert row is not None
    assert row.organization_id is None
    assert row.api_key_id is None
    assert row.status_code == 401
    assert row.error_code == "unauthorized"


async def test_integration_x_request_id_generated_when_absent(
    app_client, db_factory
):
    _, _, raw = await _org_and_key(db_factory)
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers={"Authorization": f"Bearer {raw}"},
        **_pdf_upload(email=f"{uuid4().hex}@clinic.example"),
    )
    assert resp.status_code == 201
    assert resp.headers.get("x-request-id")


async def test_integration_auth_failure_audited(app_client, db_factory):
    await _org_and_key(db_factory)
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers={"Authorization": f"Bearer {_raw_key()}"},
    )
    assert resp.status_code == 401
    async with db_factory() as session:
        result = await session.execute(
            select(AuditLog).where(
                AuditLog.action == "API_KEY_AUTH_FAILED"
            )
        )
        rows = list(result.scalars().all())
    assert any(row.metadata_.get("reason") == "unknown_api_key" for row in rows)


async def test_integration_last_used_at_updated(app_client, db_factory):
    _, key_id, raw = await _org_and_key(db_factory)
    await app_client.post(
        "/api/v1/integration/documents",
        headers={"Authorization": f"Bearer {raw}"},
        **_pdf_upload(email=f"{uuid4().hex}@clinic.example"),
    )
    async with db_factory() as session:
        result = await session.execute(
            select(OrganizationApiKey).where(OrganizationApiKey.id == key_id)
        )
        key = result.scalar_one()
    assert key.last_used_at is not None


async def test_integration_key_scoped_to_org(app_client, db_factory):
    org_a, key_a, raw_a = await _org_and_key(db_factory)
    org_b, _, _ = await _org_and_key(db_factory, name="Second Clinic")
    assert org_a != org_b

    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers={"Authorization": f"Bearer {raw_a}"},
        **_pdf_upload(email=f"{uuid4().hex}@clinic.example"),
    )
    assert resp.status_code == 201

    async with db_factory() as session:
        result = await session.execute(
            select(OrganizationApiRequest)
            .where(OrganizationApiRequest.organization_id != None)  # noqa: E711
        )
        rows = list(result.scalars().all())
    assert rows
    assert all(
        (row.organization_id, row.api_key_id) == (org_a, key_a) for row in rows
    )