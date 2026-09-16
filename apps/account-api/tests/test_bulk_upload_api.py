import json
from uuid import uuid4

from app.domain.access import AuditAction
from app.domain.api_key import hash_api_key, prefix_for_raw_key
from app.domain.medical import DocumentStatus, OrganizationStatus, OrganizationType
from app.domain.organization import (
    BatchItemStatus,
    OrganizationApiKeyStatus,
    OrganizationVerificationStatus,
)
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.organization import (
    Organization,
    OrganizationApiKey,
    OrganizationUploadBatch,
)
from sqlalchemy import func, select

BULK_SCOPE = ["organization.documents.bulk_upload"]
READ_SCOPE = ["organization.documents.read"]

_PDF = b"%PDF-1.7\n" + b"x" * 512
_PNG_AS_PDF = b"\x89PNG\r\n\x1a\nfake bytes"


def _raw_key() -> str:
    return f"ddorg_tst_{uuid4().hex}"


async def _org_with_key(
    db_factory,
    *,
    scopes: list[str] | None = None,
    name: str = "City Clinic",
    organization_id=None,
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
            permissions=scopes if scopes is not None else BULK_SCOPE,
            status=OrganizationApiKeyStatus.ACTIVE,
        )
        session.add(key)
        await session.commit()
        return organization_id, key.id, raw_key


async def _create_batch(
    app_client, raw: str, *, items: list[dict], files=None, headers=None
) -> int:
    if files is None:
        files = [
            ("files", ("a.pdf", _PDF, "application/pdf")),
            ("files", ("b.pdf", _PDF, "application/pdf")),
        ]
    return await app_client.post(
        "/api/v1/integration/documents/bulk",
        headers={**_auth(raw), **(headers or {})},
        data={"metadata": json.dumps(items)},
        files=files,
    )


def _auth(raw: str) -> dict:
    return {"Authorization": f"Bearer {raw}"}


async def test_bulk_submit_202_shape_and_side_effects(app_client, db_factory):
    org_id, key_id, raw = await _org_with_key(db_factory)

    resp = await _create_batch(
        app_client,
        raw,
        items=[
            {"patient_email": "anna@clinic.example", "external_id": "ext-a"},
            {"patient_email": "bob@clinic.example", "external_id": "ext-b"},
        ],
        headers={"X-Request-Id": "bulk-1"},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert set(body) == {
        "batch_id",
        "status",
        "total_count",
        "accepted_count",
        "failed_count",
        "idempotency_key",
    }
    assert body["status"] == "completed"
    assert body["total_count"] == 2
    assert body["accepted_count"] == 2
    assert body["failed_count"] == 0

    async with db_factory() as session:
        batch = await session.scalar(
            select(OrganizationUploadBatch)
            .where(OrganizationUploadBatch.organization_id == org_id)
            .limit(1)
        )
        assert batch is not None
        assert batch.idempotency_key is None
        assert body["batch_id"] == str(batch.id)

        count = await session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.organization_id == org_id)
        )
        assert count == 2

        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == AuditAction.INTEGRATION_DOCUMENT_UPLOADED
            )
        )
        assert audit is not None
        assert audit.metadata_.get("organization_id") == str(org_id)


async def test_bulk_submit_echoes_x_request_id(app_client, db_factory):
    _, _, raw = await _org_with_key(db_factory)
    resp = await _create_batch(
        app_client,
        raw,
        items=[{"patient_email": f"{uuid4().hex}@clinic.example"}],
        files=[("files", ("a.pdf", _PDF, "application/pdf"))],
        headers={"X-Request-Id": "echo-bulk"},
    )
    assert resp.status_code == 202
    assert resp.headers.get("x-request-id") == "echo-bulk"


async def test_bulk_idempotent_replay_returns_200(app_client, db_factory):
    org_id, _, raw = await _org_with_key(db_factory)
    headers = {"Idempotency-Key": "bulk-idem-1"}
    items = [
        {"patient_email": "anna@clinic.example", "external_id": "ext-a"},
        {"patient_email": "bob@clinic.example", "external_id": "ext-b"},
    ]

    first = await _create_batch(app_client, raw, items=items, headers=headers)
    assert first.status_code == 202

    second = await _create_batch(app_client, raw, items=items, headers=headers)
    assert second.status_code == 200
    assert second.json()["batch_id"] == first.json()["batch_id"]

    async with db_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.organization_id == org_id)
        )
    assert count == 2


async def test_bulk_requires_bulk_scope(app_client, db_factory):
    _, _, raw = await _org_with_key(db_factory, scopes=["organization.documents.upload"])
    resp = await _create_batch(
        app_client,
        raw,
        items=[{"patient_email": "anna@clinic.example"}],
        files=[("files", ("a.pdf", _PDF, "application/pdf"))],
    )
    assert resp.status_code == 403


async def test_bulk_submit_requires_auth(app_client, db_factory):
    await _org_with_key(db_factory)
    resp = await app_client.post(
        "/api/v1/integration/documents/bulk",
        data={"metadata": json.dumps([{"patient_email": "anna@clinic.example"}])},
        files=[("files", ("a.pdf", _PDF, "application/pdf"))],
    )
    assert resp.status_code in (401, 403)


async def test_bulk_count_mismatch_422(app_client, db_factory):
    _, _, raw = await _org_with_key(db_factory)
    resp = await _create_batch(
        app_client,
        raw,
        items=[{"patient_email": "anna@clinic.example"}],
        files=[
            ("files", ("a.pdf", _PDF, "application/pdf")),
            ("files", ("b.pdf", _PDF, "application/pdf")),
        ],
    )
    assert resp.status_code == 422


async def test_bulk_bad_metadata_json_422(app_client, db_factory):
    _, _, raw = await _org_with_key(db_factory)
    resp = await app_client.post(
        "/api/v1/integration/documents/bulk",
        headers=_auth(raw),
        data={"metadata": "not-json"},
        files=[("files", ("a.pdf", _PDF, "application/pdf"))],
    )
    assert resp.status_code == 422


async def test_bulk_empty_metadata_422(app_client, db_factory):
    _, _, raw = await _org_with_key(db_factory)
    resp = await app_client.post(
        "/api/v1/integration/documents/bulk",
        headers=_auth(raw),
        data={"metadata": "[]"},
        files=[("files", ("a.pdf", _PDF, "application/pdf"))],
    )
    assert resp.status_code == 422


async def test_bulk_over_limit_422(app_client, db_factory, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "integration_max_batch_size", 1)
    _, _, raw = await _org_with_key(db_factory)
    resp = await _create_batch(
        app_client,
        raw,
        items=[
            {"patient_email": "anna@clinic.example"},
            {"patient_email": "bob@clinic.example"},
        ],
    )
    assert resp.status_code == 422


async def test_bulk_partial_failure_marks_item_rejected(app_client, db_factory):
    org_id, _, raw = await _org_with_key(db_factory)
    resp = await _create_batch(
        app_client,
        raw,
        items=[
            {"patient_email": "anna@clinic.example", "external_id": "ext-ok"},
            {"patient_email": "bob@clinic.example", "external_id": "ext-bad"},
        ],
        files=[
            ("files", ("ok.pdf", _PDF, "application/pdf")),
            ("files", ("bad.pdf", _PNG_AS_PDF, "application/pdf")),
        ],
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "partial"
    assert body["accepted_count"] == 1
    assert body["failed_count"] == 1

    _, _, read_raw = await _org_with_key(
        db_factory, scopes=READ_SCOPE, organization_id=org_id, name="Reader"
    )
    items = await app_client.get(
        f"/api/v1/integration/batches/{body['batch_id']}/items",
        headers=_auth(read_raw),
    )
    assert items.status_code == 200
    item_bodies = items.json()
    bad = next(i for i in item_bodies if i["external_id"] == "ext-bad")
    assert bad["status"] == BatchItemStatus.REJECTED.value
    assert bad["error_code"] == "unsupported_file_type"


async def test_get_batch_requires_read_scope(app_client, db_factory):
    org_id, _, raw = await _org_with_key(db_factory)
    created = await _create_batch(
        app_client,
        raw,
        items=[{"patient_email": "anna@clinic.example"}],
        files=[("files", ("a.pdf", _PDF, "application/pdf"))],
    )
    batch_id = created.json()["batch_id"]

    denied = await app_client.get(
        f"/api/v1/integration/batches/{batch_id}", headers=_auth(raw)
    )
    assert denied.status_code == 403

    _, _, read_raw = await _org_with_key(db_factory, scopes=READ_SCOPE, name="Reader")
    ok = await app_client.get(
        f"/api/v1/integration/batches/{batch_id}", headers=_auth(read_raw)
    )
    assert ok.status_code == 404


async def test_get_batch_200_shape(app_client, db_factory):
    org_id, _, raw = await _org_with_key(db_factory)
    created = await _create_batch(
        app_client,
        raw,
        items=[
            {"patient_email": "anna@clinic.example", "external_id": "ext-a"},
            {"patient_email": "bob@clinic.example", "external_id": "ext-b"},
        ],
    )
    batch_id = created.json()["batch_id"]

    _, _, read_raw = await _org_with_key(
        db_factory, scopes=READ_SCOPE, organization_id=org_id, name="Reader"
    )
    resp = await app_client.get(
        f"/api/v1/integration/batches/{batch_id}", headers=_auth(read_raw)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == batch_id
    assert body["organization_id"] == str(org_id)
    assert body["status"] == "completed"
    assert body["total_count"] == 2
    assert body["accepted_count"] == 2
    assert body["failed_count"] == 0
    assert len(body["items"]) == 2
    assert all(item["status"] == "accepted" for item in body["items"])
    assert {item["external_id"] for item in body["items"]} == {"ext-a", "ext-b"}


async def test_get_batch_items_200_ordered(app_client, db_factory):
    org_id, _, raw = await _org_with_key(db_factory)
    created = await _create_batch(
        app_client,
        raw,
        items=[
            {"patient_email": "anna@clinic.example", "external_id": "ext-a"},
            {"patient_email": "bob@clinic.example", "external_id": "ext-b"},
        ],
    )
    batch_id = created.json()["batch_id"]

    _, _, read_raw = await _org_with_key(
        db_factory, scopes=READ_SCOPE, organization_id=org_id, name="Reader"
    )
    resp = await app_client.get(
        f"/api/v1/integration/batches/{batch_id}/items", headers=_auth(read_raw)
    )
    assert resp.status_code == 200
    items = resp.json()
    assert [item["item_index"] for item in items] == [0, 1]
    assert items[0]["document_type"] == "other"
    assert items[0]["document_id"] is not None
    assert items[0]["patient_email"] == "anna@clinic.example"


async def test_get_batch_document_type_round_trips(app_client, db_factory):
    org_id, _, raw = await _org_with_key(db_factory)
    created = await _create_batch(
        app_client,
        raw,
        items=[
            {
                "patient_email": "anna@clinic.example",
                "document_type": "lab_result",
                "external_id": "ext-lab",
            }
        ],
        files=[("files", ("lab.pdf", _PDF, "application/pdf"))],
    )
    batch_id = created.json()["batch_id"]

    _, _, read_raw = await _org_with_key(
        db_factory, scopes=READ_SCOPE, organization_id=org_id, name="Reader"
    )
    items = await app_client.get(
        f"/api/v1/integration/batches/{batch_id}/items", headers=_auth(read_raw)
    )
    assert items.status_code == 200
    assert items.json()[0]["document_type"] == "lab_result"

    async with db_factory() as session:
        doc = await session.scalar(
            select(Document).where(Document.external_id == "ext-lab")
        )
    assert doc is not None
    assert doc.status is DocumentStatus.PENDING