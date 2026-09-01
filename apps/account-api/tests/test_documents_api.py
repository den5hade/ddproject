from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.access import GrantStatus
from app.domain.account import RoleCode
from app.domain.medical import (
    DocumentStatus,
    EncounterStatus,
    EncounterType,
)
from app.models.access_grant import PatientAccessGrant
from app.models.document import Document
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.person import Person
from app.repositories.rbac import RbacRepository
from app.services.storage import StorageService
from sqlalchemy import func, select


def _identity() -> str:
    return f"doc_{uuid4().hex[:8]}@example.com"


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
        rbac = RbacRepository(session)
        await rbac.seed_defaults()
        await rbac.assign_roles(account_id, [RoleCode.SPECIALIST.value])
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
    encounter_id: UUID | None = None,
):
    files = {"upload": (filename, b"%PDF-1.4 test", mime)}
    data = {"title": title, "document_type": doc_type}
    if encounter_id is not None:
        data["encounter_id"] = str(encounter_id)
    return await client.post(
        f"/api/v1/patients/{patient_id}/documents",
        headers=_auth(token),
        files=files,
        data=data,
    )


async def _create_encounter(client, token: str, patient_id: str) -> UUID:
    resp = await client.post(
        f"/api/v1/patients/{patient_id}/encounters",
        headers=_auth(token),
        json={"type": "consultation", "started_at": "2026-01-01T09:00:00Z"},
    )
    assert resp.status_code == 201
    return UUID(resp.json()["id"])


async def _count_documents(db_factory) -> int:
    async with db_factory() as session:
        total = (await session.execute(select(func.count()).select_from(Document))).scalar_one()
    return total


async def test_upload_requires_auth(app_client, fake_redis):
    resp = await _upload(app_client, "no-token", str(uuid4()))
    assert resp.status_code == 401


async def test_upload_and_read_back(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)

    created = await _upload(app_client, token, patient_id, doc_type="lab_result", title="CBC")
    assert created.status_code == 201
    body = created.json()
    assert body["original_filename"] == "scan.pdf"
    assert body["mime_type"] == "application/pdf"
    assert body["status"] == "pending"
    document_id = body["id"]

    fetched = await app_client.get(f"/api/v1/documents/{document_id}", headers=_auth(token))
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "CBC"
    assert fetched.json()["document_type"] == "lab_result"

    versions = await app_client.get(
        f"/api/v1/documents/{document_id}/versions", headers=_auth(token)
    )
    assert versions.status_code == 200
    assert len(versions.json()) == 1
    assert versions.json()[0]["version"] == 1

    jobs = await app_client.get(f"/api/v1/documents/{document_id}/jobs", headers=_auth(token))
    assert jobs.status_code == 200
    assert jobs.json()[0]["job_type"] == "pdf_conversion"
    assert jobs.json()[0]["status"] == "queued"


async def test_upload_unsupported_type(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)

    resp = await _upload(app_client, token, patient_id, filename="notes.txt", mime="text/plain")
    assert resp.status_code == 415


async def test_upload_content_mismatch_rejected(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)

    files = {"upload": ("scan.pdf", b"\x89PNG\r\n\x1a\nfake bytes", "application/pdf")}
    data = {"title": "spoofed"}
    resp = await app_client.post(
        f"/api/v1/patients/{patient_id}/documents",
        headers=_auth(token),
        files=files,
        data=data,
    )
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

    fetched = await app_client.get(f"/api/v1/documents/{uuid4()}", headers=_auth(specialist))
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

    resp = await app_client.get(f"/api/v1/documents/{document_id}/download", headers=_auth(token))
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

    resp = await app_client.get(f"/api/v1/documents/{document_id}/download", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["download_url"].startswith("https://presigned.example/")
    assert resp.json()["expires_in"] == 900


async def test_upload_with_foreign_encounter_rejected(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)

    other = await _register(app_client, fake_redis, _identity())
    other_patient = await _create_patient(app_client, other)
    foreign_encounter = await _create_encounter(app_client, other, str(other_patient))

    resp = await _upload(app_client, token, str(patient_id), encounter_id=foreign_encounter)
    assert resp.status_code == 404
    assert "encounter" in resp.json()["detail"]
    assert await _count_documents(db_factory) == 0


async def test_upload_with_own_encounter_links_it(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)
    encounter_id = await _create_encounter(app_client, token, str(patient_id))

    created = await _upload(app_client, token, str(patient_id), encounter_id=encounter_id)
    assert created.status_code == 201
    assert UUID(created.json()["encounter_id"]) == encounter_id


async def test_encounter_listing_isolation(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    account_id = await _account_id(app_client, token)
    patient_a = await _create_patient(app_client, token)

    async with db_factory() as session:
        person = Person()
        session.add(person)
        await session.flush()
        patient_b = Patient(person_id=person.id)
        session.add(patient_b)
        await session.flush()
        record_b = MedicalRecord(patient_id=patient_b.id)
        session.add(record_b)
        await session.flush()
        encounter_b = Encounter(
            medical_record_id=record_b.id,
            type=EncounterType.CONSULTATION,
            status=EncounterStatus.SCHEDULED,
            started_at=datetime.now(UTC),
        )
        session.add(encounter_b)
        await session.flush()

        record_a = await session.scalar(
            select(MedicalRecord).where(MedicalRecord.patient_id == patient_a)
        )
        session.add(
            Document(
                medical_record_id=record_a.id,
                encounter_id=encounter_b.id,
                original_filename="evil.pdf",
                mime_type="application/pdf",
                size_bytes=10,
                storage_key="",
                status=DocumentStatus.PENDING,
            )
        )
        await session.commit()
        foreign_patient_id, foreign_encounter_id = patient_b.id, encounter_b.id

    await _grant(db_factory, foreign_patient_id, account_id, view=True)

    resp = await app_client.get(
        f"/api/v1/encounters/{foreign_encounter_id}/documents", headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_version_upload_no_longer_routes_by_encounter(app_client, fake_redis):
    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)
    encounter_id = await _create_encounter(app_client, token, str(patient_id))
    created = await _upload(app_client, token, str(patient_id), encounter_id=encounter_id)
    document_id = created.json()["id"]

    versioned = await app_client.post(
        f"/api/v1/documents/{document_id}/versions",
        headers=_auth(token),
        files={"upload": ("v2.pdf", b"%PDF-1.4 v2", "application/pdf")},
        data={"title": "v2", "document_type": "other", "encounter_id": str(uuid4())},
    )
    assert versioned.status_code in (200, 201)

    fetched = await app_client.get(f"/api/v1/documents/{document_id}", headers=_auth(token))
    assert fetched.status_code == 200
    assert UUID(fetched.json()["encounter_id"]) == encounter_id


async def _override_service_with_storage(db_factory, storage):
    from app.core.database import get_db
    from app.dependencies.documents import get_document_service
    from app.main import app
    from app.services.documents import DocumentService
    from fastapi import Depends

    async def _override(session=Depends(get_db)) -> DocumentService:
        return DocumentService(session=session, publisher=None, storage=storage)

    app.dependency_overrides[get_document_service] = _override


class FakeMarkdownStorage(StorageService):
    def __init__(self, canonical: dict | None = None, markdown: str | None = None):
        super().__init__(None)
        self._canonical = canonical
        self._markdown = markdown

    def markdown_object_key(self, *, patient_id, document_id, version_id, kind) -> str:
        filename = "canonical.json" if kind == "canonical" else f"{kind}.md"
        return (
            f"tenants/default/patients/{patient_id}/documents/{document_id}"
            f"/versions/{version_id}/{filename}"
        )

    async def download_json(self, key: str) -> dict | None:
        return self._canonical

    async def download_text(self, key: str) -> str | None:
        return self._markdown


async def _stored_version(db_factory, document_id: str) -> None:
    from app.models.document import DocumentVersion

    async with db_factory() as session:
        version = await session.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == UUID(document_id))
        )
        version.s3_key = "tenants/default/patients/x/documents/y/versions/z/original.pdf"
        await session.commit()


async def test_markdown_no_stored_version_404(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)
    created = await _upload(app_client, token, patient_id)
    document_id = created.json()["id"]

    resp = await app_client.get(f"/api/v1/documents/{document_id}/markdown", headers=_auth(token))
    assert resp.status_code == 404


async def test_markdown_returns_empty_when_no_artifacts(app_client, fake_redis, db_factory):
    await _override_service_with_storage(db_factory, FakeMarkdownStorage())
    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)
    created = await _upload(app_client, token, patient_id)
    document_id = created.json()["id"]
    await _stored_version(db_factory, document_id)

    resp = await app_client.get(f"/api/v1/documents/{document_id}/markdown", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_canonical"] is False
    assert body["canonical"] is None
    assert body["canonical_key"] is None
    assert body["structured_markdown"] is None


async def test_markdown_returns_inline_canonical(app_client, fake_redis, db_factory):
    canonical = {"type": "generic", "subtype": "generic", "fields": {"note": "x"}}
    await _override_service_with_storage(
        db_factory, FakeMarkdownStorage(canonical=canonical, markdown="# body")
    )
    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)
    created = await _upload(app_client, token, patient_id)
    document_id = created.json()["id"]
    await _stored_version(db_factory, document_id)

    resp = await app_client.get(f"/api/v1/documents/{document_id}/markdown", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_canonical"] is True
    assert body["canonical"] == canonical
    assert body["canonical_key"].endswith("/canonical.json")
    assert body["structured_markdown"] == "# body"


async def _add_succeeded_extraction(db_factory, document_id: str) -> None:
    from uuid import uuid4

    from app.domain.medical import ExtractionStatus
    from app.models.extraction import DocumentExtraction

    async with db_factory() as session:
        extraction = DocumentExtraction(
            id=uuid4(),
            document_id=UUID(document_id),
            schema_name="laboratory",
            schema_version="1.0.0",
            status=ExtractionStatus.SUCCEEDED,
            confidence=1.0,
            data={"type": "laboratory", "canonical_key": "k", "structured_key": "s"},
        )
        session.add(extraction)
        await session.commit()


async def test_canonical_returns_persisted_data(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)
    created = await _upload(app_client, token, patient_id)
    document_id = created.json()["id"]
    await _add_succeeded_extraction(db_factory, document_id)

    resp = await app_client.get(f"/api/v1/documents/{document_id}/canonical", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_name"] == "laboratory"
    assert body["schema_version"] == "1.0.0"
    assert body["confidence"] == 1.0
    assert body["data"]["type"] == "laboratory"
    assert body["data"]["canonical_key"] == "k"
    assert body["data"]["structured_key"] == "s"


async def test_canonical_404_when_no_succeeded_extraction(app_client, fake_redis, db_factory):
    token = await _register(app_client, fake_redis, _identity())
    patient_id = await _create_patient(app_client, token)
    created = await _upload(app_client, token, patient_id)
    document_id = created.json()["id"]

    resp = await app_client.get(f"/api/v1/documents/{document_id}/canonical", headers=_auth(token))
    assert resp.status_code == 404
