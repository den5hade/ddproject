import asyncio
from uuid import UUID, uuid4

from app.domain.access import AuditAction
from app.domain.api_key import hash_api_key, prefix_for_raw_key
from app.domain.medical import DocumentStatus, OrganizationStatus, OrganizationType
from app.domain.organization import (
    OrganizationApiKeyStatus,
    OrganizationVerificationStatus,
)
from app.models.account import Account
from app.models.audit_log import AuditLog
from app.models.medical_record import MedicalRecord
from app.models.organization import (
    Organization,
    OrganizationApiKey,
    OrganizationApiRequest,
)
from app.models.patient import Patient
from sqlalchemy import func, select

UPLOAD_SCOPE = ["organization.documents.upload"]
READ_SCOPE = ["organization.documents.read"]


def _raw_key() -> str:
    return f"ddorg_tst_{uuid4().hex}"


_PDF = b"%PDF-1.7\n" + b"x" * 512


def _pdf_upload(
    email: str = "anna@clinic.example",
    *,
    data: dict | None = None,
    content: bytes = _PDF,
) -> dict:
    body = {"patient_email": email}
    if data:
        body.update(data)
    return {
        "files": {"upload": ("scan.pdf", content, "application/pdf")},
        "data": body,
    }


async def _org_with_key(
    db_factory,
    *,
    scopes: list[str] | None = None,
    organization_id=None,
    name: str = "City Clinic",
):
    raw_key = _raw_key()
    async with db_factory() as session:
        if organization_id is None:
            org = Organization(
                name=name,
                type=OrganizationType.CLINIC,
                status=OrganizationStatus.ACTIVE,
            )
            org.verification_status = OrganizationVerificationStatus.VERIFIED
            session.add(org)
            await session.flush()
            organization_id = org.id
        key = OrganizationApiKey(
            organization_id=organization_id,
            name="demo",
            prefix=prefix_for_raw_key(raw_key),
            key_hash=hash_api_key(raw_key),
            permissions=scopes if scopes is not None else UPLOAD_SCOPE,
            status=OrganizationApiKeyStatus.ACTIVE,
        )
        session.add(key)
        await session.commit()
        return organization_id, key.id, raw_key


async def _account_for_email(db_factory, email: str) -> Account | None:
    async with db_factory() as session:
        return await session.scalar(
            select(Account).where(Account.email_normalized == email)
        )


@staticmethod
def _auth(raw: str) -> dict:
    return {"Authorization": f"Bearer {raw}"}


async def test_submit_document_201_shape_and_side_effects(app_client, db_factory):
    org_id, key_id, raw = await _org_with_key(db_factory)

    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers={**_auth(raw), "X-Request-Id": "req-4d-1"},
        **_pdf_upload(
            email="anna@clinic.example", data={"external_id": "ext-42", "title": "CBC"}
        ),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {"document_id", "status", "external_id", "patient_id"}
    assert body["status"] == "processing"
    assert body["external_id"] == "ext-42"

    account = await _account_for_email(db_factory, "anna@clinic.example")
    assert account is not None
    assert account.status.value == "pending"

    async with db_factory() as session:
        patient = await session.scalar(
            select(Patient).where(Patient.person_id == account.person_id)
        )
        assert patient is not None
        record = await session.scalar(
            select(MedicalRecord).where(MedicalRecord.patient_id == patient.id)
        )
        assert record is not None
        assert body["patient_id"] == str(patient.id)

        usage = await session.scalar(
            select(OrganizationApiRequest).where(
                OrganizationApiRequest.request_id == "req-4d-1"
            )
        )
        assert usage is not None
        assert usage.organization_id == org_id
        assert usage.api_key_id == key_id
        assert usage.status_code == 201

        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == AuditAction.INTEGRATION_DOCUMENT_UPLOADED,
                AuditLog.resource_id == UUID(body["document_id"]),
            )
        )
        assert audit is not None
        assert audit.metadata_.get("organization_id") == str(org_id)
        assert audit.metadata_.get("external_id") == "ext-42"


async def test_submit_document_echoes_x_request_id(app_client, db_factory):
    _, _, raw = await _org_with_key(db_factory)
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers={**_auth(raw), "X-Request-Id": "echo-1"},
        **_pdf_upload(email=f"{uuid4().hex}@clinic.example"),
    )
    assert resp.status_code == 201
    assert resp.headers.get("x-request-id") == "echo-1"


async def test_submit_document_rejects_invalid_document_type(app_client, db_factory):
    _, _, raw = await _org_with_key(db_factory)
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers=_auth(raw),
        **_pdf_upload(data={"document_type": "not_a_type"}),
    )
    assert resp.status_code == 422


async def test_submit_document_rejects_phone_identity(app_client, db_factory):
    _, _, raw = await _org_with_key(db_factory)
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers=_auth(raw),
        **_pdf_upload(email="+79991234567"),
    )
    assert resp.status_code == 422


async def test_submit_document_requires_patient_email(app_client, db_factory):
    _, _, raw = await _org_with_key(db_factory)
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers=_auth(raw),
        files={"upload": ("scan.pdf", _PDF, "application/pdf")},
        data={},
    )
    assert resp.status_code == 422


async def test_submit_document_rejects_mime_mismatch(app_client, db_factory):
    _, _, raw = await _org_with_key(db_factory)
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers=_auth(raw),
        files={
            "upload": ("scan.pdf", b"\x89PNG\r\n\x1a\nfake bytes", "application/pdf")
        },
        data={"patient_email": f"{uuid4().hex}@clinic.example"},
    )
    assert resp.status_code == 415


async def test_submit_document_rejects_oversized_upload(
    app_client, db_factory, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_upload_bytes", 4)
    _, _, raw = await _org_with_key(db_factory)
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers=_auth(raw),
        **_pdf_upload(email=f"{uuid4().hex}@clinic.example"),
    )
    assert resp.status_code == 413


async def test_submit_document_unknown_branch_404(app_client, db_factory):
    _, _, raw = await _org_with_key(db_factory)
    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers=_auth(raw),
        **_pdf_upload(data={"branch_code": "no-such-branch"}),
    )
    assert resp.status_code == 404


async def test_submit_document_idempotent_replay_by_external_id(
    app_client, db_factory
):
    _, _, raw = await _org_with_key(db_factory)
    headers = _auth(raw)
    kwargs = _pdf_upload(
        email="anna@clinic.example", data={"external_id": "ext-replay"}
    )

    first = await app_client.post("/api/v1/integration/documents", headers=headers, **kwargs)
    assert first.status_code == 201
    second = await app_client.post("/api/v1/integration/documents", headers=headers, **kwargs)
    assert second.status_code == 200
    assert second.json()["document_id"] == first.json()["document_id"]


async def test_submit_document_replay_by_idempotency_key_header(
    app_client, db_factory
):
    _, _, raw = await _org_with_key(db_factory)
    headers = {**_auth(raw), "Idempotency-Key": "idem-7"}
    kwargs = _pdf_upload(email="anna@clinic.example")

    first = await app_client.post("/api/v1/integration/documents", headers=headers, **kwargs)
    assert first.status_code == 201
    second = await app_client.post("/api/v1/integration/documents", headers=headers, **kwargs)
    assert second.status_code == 200
    assert second.json()["document_id"] == first.json()["document_id"]


async def test_submit_document_conflicting_keys_409(app_client, db_factory):
    _, _, raw = await _org_with_key(db_factory)
    headers = {**_auth(raw), "Idempotency-Key": "req-b"}
    await app_client.post(
        "/api/v1/integration/documents",
        headers=_auth(raw),
        **_pdf_upload(data={"external_id": "ext-a"}),
    )
    await app_client.post(
        "/api/v1/integration/documents",
        headers=headers,
        **_pdf_upload(data={"external_id": "ext-b"}),
    )

    resp = await app_client.post(
        "/api/v1/integration/documents",
        headers=headers,
        **_pdf_upload(data={"external_id": "ext-a"}),
    )
    assert resp.status_code == 409


async def test_get_document_status_scoped_to_organization(app_client, db_factory):
    org_a, _, raw_a = await _org_with_key(db_factory)
    _, _, foreign_raw = await _org_with_key(db_factory, name="Second Clinic")

    upload = await app_client.post(
        "/api/v1/integration/documents",
        headers=_auth(raw_a),
        **_pdf_upload(data={"external_id": "ext-get"}),
    )
    document_id = upload.json()["document_id"]

    missing_read = await app_client.get(
        f"/api/v1/integration/documents/{document_id}",
        headers=_auth(raw_a),
    )
    assert missing_read.status_code == 403

    _, _, read_raw = await _org_with_key(
        db_factory, scopes=READ_SCOPE, organization_id=org_a
    )
    ok = await app_client.get(
        f"/api/v1/integration/documents/{document_id}",
        headers=_auth(read_raw),
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["document_id"] == document_id
    assert body["external_id"] == "ext-get"
    assert body["status"] == DocumentStatus.PENDING.value
    assert body["organization_id"] == str(org_a)

    foreign = await app_client.get(
        f"/api/v1/integration/documents/{document_id}",
        headers=_auth(foreign_raw),
    )
    assert foreign.status_code == 403

    foreign_read, _, read_foreign_raw = await _org_with_key(
        db_factory, scopes=READ_SCOPE, name="Foreign Reader"
    )
    assert foreign_read != org_a
    forbidden = await app_client.get(
        f"/api/v1/integration/documents/{document_id}",
        headers=_auth(read_foreign_raw),
    )
    assert forbidden.status_code == 404


async def test_concurrent_submissions_are_isolated(app_client, db_factory):
    _, _, raw = await _org_with_key(db_factory)
    headers = _auth(raw)

    async def submit(index: int):
        return await app_client.post(
            "/api/v1/integration/documents",
            headers=headers,
            **_pdf_upload(email=f"user{index}@clinic.example"),
        )

    responses = await asyncio.gather(submit(1), submit(2))
    assert [r.status_code for r in responses] == [201, 201]
    account = await _account_for_email(db_factory, "user1@clinic.example")
    assert account is not None
    async with db_factory() as session:
        total = await session.scalar(select(func.count()).select_from(Account))
    assert total == 2


async def test_same_email_submissions_dedupe_to_one_patient(
    app_client, db_factory
):
    _, _, raw = await _org_with_key(db_factory)
    headers = _auth(raw)

    first = await app_client.post(
        "/api/v1/integration/documents",
        headers=headers,
        **_pdf_upload(email="shared@clinic.example"),
    )
    assert first.status_code == 201
    second = await app_client.post(
        "/api/v1/integration/documents",
        headers=headers,
        **_pdf_upload(email="shared@clinic.example"),
    )
    assert second.status_code == 201
    assert second.json()["patient_id"] == first.json()["patient_id"]

    account = await _account_for_email(db_factory, "shared@clinic.example")
    assert account is not None
    async with db_factory() as session:
        patients = await session.scalar(
            select(func.count())
            .select_from(Patient)
            .where(Patient.person_id == account.person_id)
        )
    assert patients == 1