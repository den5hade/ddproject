from uuid import UUID, uuid4

from app.domain.access import GrantStatus
from app.models.access_grant import PatientAccessGrant
from sqlalchemy import select


def _identity() -> str:
    return f"doc_{uuid4().hex[:8]}@example.com"


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


async def _grant(db_factory, patient_id, account_id, *, upload=False, view=False) -> None:
    async with db_factory() as session:
        session.add(
            PatientAccessGrant(
                patient_id=patient_id,
                account_id=account_id,
                status=GrantStatus.ACTIVE,
                can_upload_documents=upload,
                can_view_documents=view,
            )
        )
        await session.commit()


async def _upload(
    client,
    token: str,
    patient_id: str,
    *,
    filename: str = "scan.pdf",
    mime: str = "application/pdf",
    title: str = "Blood test",
    doc_type: str = "other",
):
    files = {"upload": (filename, b"%PDF-1.4 test", mime)}
    data = {"title": title, "document_type": doc_type}
    return await client.post(
        f"/api/v1/patients/{patient_id}/documents",
        headers=_auth(token),
        files=files,
        data=data,
    )


async def test_upload_requires_auth(app_client, fake_redis):
    resp = await _upload(app_client, "no-token", str(uuid4()))
    assert resp.status_code == 401


async def test_upload_and_read_back(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)

    created = await _upload(
        app_client, token, patient_id, doc_type="lab_result", title="CBC"
    )
    assert created.status_code == 201
    body = created.json()
    assert body["original_filename"] == "scan.pdf"
    assert body["mime_type"] == "application/pdf"
    assert body["status"] == "pending"
    document_id = body["id"]

    fetched = await app_client.get(
        f"/api/v1/documents/{document_id}", headers=_auth(token)
    )
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "CBC"
    assert fetched.json()["document_type"] == "lab_result"

    versions = await app_client.get(
        f"/api/v1/documents/{document_id}/versions", headers=_auth(token)
    )
    assert versions.status_code == 200
    assert len(versions.json()) == 1
    assert versions.json()[0]["version"] == 1

    jobs = await app_client.get(
        f"/api/v1/documents/{document_id}/jobs", headers=_auth(token)
    )
    assert jobs.status_code == 200
    assert jobs.json()[0]["job_type"] == "pdf_conversion"
    assert jobs.json()[0]["status"] == "queued"


async def test_upload_unsupported_type(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)

    resp = await _upload(app_client, token, patient_id, filename="notes.txt", mime="text/plain")
    assert resp.status_code == 415


async def test_upload_too_large(app_client, fake_redis, monkeypatch):
    from app.core.config import settings

    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)

    monkeypatch.setattr(settings, "max_upload_bytes", 4)
    resp = await _upload(app_client, token, patient_id)
    assert resp.status_code == 413


async def test_upload_quota_enforced(app_client, fake_redis, monkeypatch):
    import app.services.documents as documents_module

    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)

    monkeypatch.setattr(documents_module, "FREE_DOCUMENT_LIMIT", 1)
    first = await _upload(app_client, token, patient_id)
    assert first.status_code == 201
    second = await _upload(app_client, token, patient_id, filename="second.pdf")
    assert second.status_code == 429


async def test_subscribed_account_skips_quota(app_client, fake_redis, monkeypatch, db_factory):
    import app.services.documents as documents_module
    from app.models.account import Account

    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    patient_id = await _create_patient(app_client, token)

    async with db_factory() as session:
        account = await session.get(Account, account_id)
        account.is_subscribed = True
        await session.commit()

    monkeypatch.setattr(documents_module, "FREE_DOCUMENT_LIMIT", 1)
    first = await _upload(app_client, token, patient_id)
    second = await _upload(app_client, token, patient_id, filename="second.pdf")
    assert first.status_code == 201
    assert second.status_code == 201


async def test_specialist_without_grant_403(app_client, fake_redis, db_factory):
    owner = await _register(app_client, fake_redis, _identity())
    specialist = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, owner)

    resp = await _upload(app_client, specialist, patient_id)
    assert resp.status_code == 403

    fetched = await app_client.get(
        f"/api/v1/documents/{uuid4()}", headers=_auth(specialist)
    )
    assert fetched.status_code in (403, 404)


async def test_specialist_with_upload_grant_ok(app_client, fake_redis, db_factory):
    owner = await _register(app_client, fake_redis, _identity())
    specialist = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, owner)
    specialist_id = await _account_id(app_client, specialist)
    await _grant(db_factory, patient_id, specialist_id, upload=True)

    resp = await _upload(app_client, specialist, patient_id)
    assert resp.status_code == 201


async def test_download_without_storage_503(app_client, fake_redis, db_factory):

    from app.models.document import DocumentVersion

    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)
    created = await _upload(app_client, token, patient_id)
    document_id = UUID(created.json()["id"])

    async with db_factory() as session:
        version = await session.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == document_id)
        )
        version.s3_key = "tenants/default/patients/x/documents/y/versions/z/original.pdf"
        await session.commit()

    resp = await app_client.get(
        f"/api/v1/documents/{document_id}/download", headers=_auth(token)
    )
    assert resp.status_code == 503


async def test_download_returns_presigned_url(app_client, fake_redis, db_factory):
    from app.core.database import get_db
    from app.dependencies.documents import get_document_service
    from app.main import app
    from app.models.document import DocumentVersion
    from app.services.documents import DocumentService
    from app.services.storage import StorageService
    from fastapi import Depends

    class FakeStorage(StorageService):
        def __init__(self):
            super().__init__(None)

        def download_url(self, key, filename=None, expires_in=900):
            return f"https://presigned.example/{key}"

    async def _override(session=Depends(get_db)) -> DocumentService:
        return DocumentService(session=session, publisher=None, storage=FakeStorage())

    app.dependency_overrides[get_document_service] = _override

    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)
    created = await _upload(app_client, token, patient_id)
    document_id = UUID(created.json()["id"])

    async with db_factory() as session:
        version = await session.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == document_id)
        )
        version.s3_key = "tenants/default/patients/x/documents/y/versions/z/original.pdf"
        await session.commit()

    resp = await app_client.get(
        f"/api/v1/documents/{document_id}/download", headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["download_url"].startswith("https://presigned.example/")
    assert resp.json()["expires_in"] == 900