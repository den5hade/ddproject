from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.domain.access import AuditAction
from app.domain.medical import (
    OrganizationStatus,
    OrganizationType,
)
from app.domain.organization import (
    BatchItemStatus,
    BatchStatus,
    BranchStatus,
    OrganizationBatchNotFoundError,
    OrganizationBatchSizeLimitExceededError,
)
from app.models.account import Account
from app.models.audit_log import AuditLog
from app.models.organization import (
    Organization,
    OrganizationBranch,
)
from app.schemas.integration import BulkUploadItemMetadata, BulkUploadRequest
from app.services.organization_bulk_upload import OrganizationBulkUploadService
from contracts.events import (
    OrganizationBatchCompleted,
    OrganizationBatchCreated,
    OrganizationDocumentSubmitted,
)
from fastapi import UploadFile
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[4]

_PDF = b"%PDF-1.7\n" + b"x" * 512
_PNG_AS_PDF = b"\x89PNG\r\n\x1a\nfake bytes"


class FakePublisher:
    def __init__(self):
        self.published = []

    async def publish(self, routing_key: str, event) -> None:
        self.published.append((routing_key, event))


def _upload(name: str = "cbc.pdf", content: bytes = _PDF) -> UploadFile:
    return UploadFile(
        file=BytesIO(content), filename=name, headers={"content-type": "application/pdf"}
    )


def _uploads(count: int) -> list[UploadFile]:
    return [_upload(f"scan-{i}.pdf") for i in range(count)]


def _request_with_factory(db_factory) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(api_request_db_factory=db_factory)),
        headers={},
        client=None,
    )


def _bulk_service(db_session, db_factory, *, publisher=None) -> OrganizationBulkUploadService:
    return OrganizationBulkUploadService(
        db_session, publisher=publisher
    )


def _payload(items: list[dict], key: str | None = None) -> BulkUploadRequest:
    return BulkUploadRequest(
        items=[BulkUploadItemMetadata.model_validate(item) for item in items],
        idempotency_key=key,
    )


async def _patient_account(db_session):
    from app.services.patient import PatientService

    account = Account(id=uuid4())
    db_session.add(account)
    await db_session.flush()
    return await PatientService(db_session).ensure_patient_for_account(account)


async def _organization(db_session, *, branch_status: BranchStatus = BranchStatus.ACTIVE):
    org = Organization(
        id=uuid4(),
        name="City Clinic",
        type=OrganizationType.CLINIC,
        status=OrganizationStatus.ACTIVE,
    )
    db_session.add(org)
    await db_session.flush()
    branch = OrganizationBranch(
        organization_id=org.id, code="main", name="Main", status=branch_status
    )
    db_session.add(branch)
    await db_session.flush()
    return org, branch


async def _audit_for(db_session, action: AuditAction):
    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == action)
    )
    return list(result.scalars().all())


async def test_create_batch_persists_header_and_items(db_session, db_factory):
    org, _ = await _organization(db_session)
    service = _bulk_service(db_session, db_factory)
    request = _request_with_factory(db_factory)

    batch, replayed = await service.create_batch(
        organization_id=org.id,
        api_key_id=uuid4(),
        payload=_payload(
            [
                {"patient_email": "anna@clinic.example", "external_id": "ext-1"},
                {"patient_email": "bob@clinic.example", "external_id": "ext-2"},
            ],
            key="req-1",
        ),
        request=request,
    )

    assert replayed is False
    assert batch.status is BatchStatus.ACCEPTED
    assert batch.total_count == 2
    assert batch.accepted_count == 0
    assert batch.failed_count == 0
    assert batch.completed_at is None

    items = await service.get_batch_items(org.id, batch.id)
    assert [item.item_index for item in items] == [0, 1]
    assert all(item.status is BatchItemStatus.PENDING for item in items)
    assert items[0].external_id == "ext-1"

    audits = await _audit_for(db_session, AuditAction.INTEGRATION_BATCH_CREATED)
    assert len(audits) == 1
    assert audits[0].resource_id == batch.id


async def test_create_batch_rejects_over_size_limit(
    db_session, db_factory, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "integration_max_batch_size", 2)
    org, _ = await _organization(db_session)
    service = _bulk_service(db_session, db_factory)

    with pytest.raises(OrganizationBatchSizeLimitExceededError):
        await service.create_batch(
            organization_id=org.id,
            api_key_id=uuid4(),
            payload=_payload(
                [
                    {"patient_email": f"user-{i}@clinic.example"}
                    for i in range(3)
                ]
            ),
            request=_request_with_factory(db_factory),
        )


async def test_submit_accepts_all_items_and_finalizes_completed(
    db_session, db_factory
):
    org, _ = await _organization(db_session)
    publisher = FakePublisher()
    service = _bulk_service(db_session, db_factory, publisher=publisher)
    request = _request_with_factory(db_factory)

    result = await service.submit_batch(
        organization_id=org.id,
        api_key_id=uuid4(),
        payload=_payload(
            [
                {"patient_email": "anna@clinic.example", "external_id": "ext-1"},
                {"patient_email": "bob@clinic.example", "external_id": "ext-2"},
            ],
            key="req-batch",
        ),
        files=_uploads(2),
        request=request,
    )

    assert result.replayed is False
    batch = result.batch
    assert batch.status is BatchStatus.COMPLETED
    assert batch.total_count == 2
    assert batch.accepted_count == 2
    assert batch.failed_count == 0
    assert batch.completed_at is not None

    items = await service.get_batch_items(org.id, batch.id)
    assert all(item.status is BatchItemStatus.ACCEPTED for item in items)
    assert all(item.document_id is not None for item in items)
    assert items[0].document_id != items[1].document_id

    kinds = [key for key, _ in publisher.published]
    assert "organization.batch.created" in kinds
    assert kinds.count("organization.document.submitted") == 2
    assert "organization.batch.completed" in kinds

    created = next(
        e for key, e in publisher.published if key == "organization.batch.created"
    )
    assert isinstance(created, OrganizationBatchCreated)
    assert created.batch_id == batch.id
    assert created.total_count == 2

    completed = next(
        e for key, e in publisher.published if key == "organization.batch.completed"
    )
    assert isinstance(completed, OrganizationBatchCompleted)
    assert completed.status == "completed"
    assert completed.accepted_count == 2
    assert completed.failed_count == 0

    submitted = [
        e
        for key, e in publisher.published
        if key == "organization.document.submitted"
    ]
    assert all(isinstance(e, OrganizationDocumentSubmitted) for e in submitted)
    assert {e.external_id for e in submitted} == {"ext-1", "ext-2"}

    audit = await _audit_for(db_session, AuditAction.INTEGRATION_DOCUMENT_UPLOADED)
    assert len(audit) == 2


async def test_submit_replays_by_idempotency_key(db_session, db_factory):
    org, _ = await _organization(db_session)
    service = _bulk_service(db_session, db_factory)
    request = _request_with_factory(db_factory)
    payload = _payload(
        [
            {"patient_email": "anna@clinic.example", "external_id": "ext-1"},
            {"patient_email": "bob@clinic.example", "external_id": "ext-2"},
        ],
        key="req-1",
    )

    first = await service.submit_batch(
        organization_id=org.id,
        api_key_id=uuid4(),
        payload=payload,
        files=_uploads(2),
        request=request,
    )
    assert first.replayed is False
    assert first.batch.status is BatchStatus.COMPLETED

    second = await service.submit_batch(
        organization_id=org.id,
        api_key_id=uuid4(),
        payload=payload,
        files=_uploads(2),
        request=request,
    )

    assert second.replayed is True
    assert second.batch.id == first.batch.id

    from app.models.document import Document

    documents = await db_session.execute(
        select(Document.id).where(Document.organization_id == org.id)
    )
    assert len(documents.scalars().all()) == 2
    docs = await _audit_for(db_session, AuditAction.INTEGRATION_DOCUMENT_UPLOADED)
    assert len(docs) == 2


async def test_submit_partial_failure_marks_item_rejected(db_session, db_factory):
    org, _ = await _organization(db_session)
    publisher = FakePublisher()
    service = _bulk_service(db_session, db_factory, publisher=publisher)
    request = _request_with_factory(db_factory)

    result = await service.submit_batch(
        organization_id=org.id,
        api_key_id=uuid4(),
        payload=_payload(
            [
                {"patient_email": "anna@clinic.example", "external_id": "ext-ok"},
                {"patient_email": "bob@clinic.example", "external_id": "ext-bad"},
            ]
        ),
        files=[
            _upload("ok.pdf"),
            _upload("bad.pdf", content=_PNG_AS_PDF),
        ],
        request=request,
    )

    batch = result.batch
    assert batch.status is BatchStatus.PARTIAL
    assert batch.accepted_count == 1
    assert batch.failed_count == 1

    items = await service.get_batch_items(org.id, batch.id)
    assert items[0].status is BatchItemStatus.ACCEPTED
    assert items[0].error_code is None
    assert items[1].status is BatchItemStatus.REJECTED
    assert items[1].error_code == "unsupported_file_type"
    assert items[1].error_message

    completed = next(
        e for key, e in publisher.published if key == "organization.batch.completed"
    )
    assert completed.status == "partial"
    assert completed.accepted_count == 1
    assert completed.failed_count == 1


async def test_submit_rejects_duplicate_external_id(db_session, db_factory):
    org, _ = await _organization(db_session)
    service = _bulk_service(db_session, db_factory)

    result = await service.submit_batch(
        organization_id=org.id,
        api_key_id=uuid4(),
        payload=_payload(
            [
                {"patient_email": "anna@clinic.example", "external_id": "dup-1"},
                {"patient_email": "bob@clinic.example", "external_id": "dup-1"},
            ]
        ),
        files=_uploads(2),
        request=_request_with_factory(db_factory),
    )

    assert result.batch.status is BatchStatus.PARTIAL
    assert result.batch.accepted_count == 1
    assert result.batch.failed_count == 1

    items = await service.get_batch_items(org.id, result.batch.id)
    assert items[1].status is BatchItemStatus.REJECTED
    assert items[1].error_code == "duplicate_external_id"


async def test_submit_rejects_unknown_branch(db_session, db_factory):
    org, _ = await _organization(db_session)
    service = _bulk_service(db_session, db_factory)

    result = await service.submit_batch(
        organization_id=org.id,
        api_key_id=uuid4(),
        payload=_payload(
            [{"patient_email": "anna@clinic.example", "branch_code": "no-code"}]
        ),
        files=_uploads(1),
        request=_request_with_factory(db_factory),
    )

    assert result.batch.status is BatchStatus.FAILED
    assert result.batch.accepted_count == 0
    assert result.batch.failed_count == 1
    items = await service.get_batch_items(org.id, result.batch.id)
    assert items[0].error_code == "branch_not_found"


async def test_get_batch_is_organization_scoped(db_session, db_factory):
    org_a, _ = await _organization(db_session)
    org_b, _ = await _organization(db_session)
    service = _bulk_service(db_session, db_factory)

    result = await service.submit_batch(
        organization_id=org_a.id,
        api_key_id=uuid4(),
        payload=_payload([{"patient_email": "anna@clinic.example"}]),
        files=_uploads(1),
        request=_request_with_factory(db_factory),
    )

    assert (await service.get_batch(org_a.id, result.batch.id)).id == result.batch.id
    with pytest.raises(OrganizationBatchNotFoundError):
        await service.get_batch(org_b.id, result.batch.id)

    with pytest.raises(OrganizationBatchNotFoundError):
        await service.get_batch_items(org_b.id, result.batch.id)

    items = await service.get_batch_items(org_a.id, result.batch.id)
    assert len(items) == 1
    assert items[0].item_index == 0


def _load_migration_0013():
    path = REPO_ROOT / "migrations/alembic/versions/0013_organization_upload_batches.py"
    spec = spec_from_file_location("migration_0013", path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_0013_revision_wiring() -> None:
    migration = _load_migration_0013()
    assert migration.revision == "0013"
    assert migration.down_revision == "0012"


def test_migration_0013_upgrade_downgrade_round_trip() -> None:
    migration = _load_migration_0013()
    engine = sa.create_engine("sqlite://")
    org_id, key_id, doc_id, batch_id, item_id = (uuid4() for _ in range(5))
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                CREATE TABLE organizations (
                    id VARCHAR(32) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL
                )
                """
            )
        )
        conn.execute(
            sa.text(
                """
                CREATE TABLE organization_api_keys (
                    id VARCHAR(32) PRIMARY KEY,
                    organization_id VARCHAR(32) NOT NULL,
                    name VARCHAR(255) NOT NULL
                )
                """
            )
        )
        conn.execute(
            sa.text(
                """
                CREATE TABLE documents (
                    id VARCHAR(32) PRIMARY KEY,
                    medical_record_id VARCHAR(32) NOT NULL,
                    status VARCHAR(16) NOT NULL
                )
                """
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name) VALUES (:id, 'City Clinic')"
            ).bindparams(id=org_id.hex)
        )
        conn.execute(
            sa.text(
                "INSERT INTO organization_api_keys (id, organization_id, name)"
                " VALUES (:id, :org, 'demo')"
            ).bindparams(id=key_id.hex, org=org_id.hex)
        )
        conn.execute(
            sa.text(
                "INSERT INTO documents (id, medical_record_id, status)"
                " VALUES (:id, 'm1', 'PENDING')"
            ).bindparams(id=doc_id.hex)
        )

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()
        tables = {
            row[0]
            for row in conn.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        assert "organization_upload_batches" in tables
        assert "organization_upload_batch_items" in tables

        batch_columns = {
            row[1]
            for row in conn.execute(
                sa.text("PRAGMA table_info(organization_upload_batches)")
            )
        }
        assert {
            "id",
            "organization_id",
            "api_key_id",
            "idempotency_key",
            "status",
            "total_count",
            "accepted_count",
            "failed_count",
            "created_at",
            "completed_at",
        } <= batch_columns
        item_columns = {
            row[1]
            for row in conn.execute(
                sa.text("PRAGMA table_info(organization_upload_batch_items)")
            )
        }
        assert {
            "id",
            "batch_id",
            "document_id",
            "item_index",
            "patient_email",
            "document_type",
            "external_id",
            "branch_code",
            "title",
            "status",
            "error_code",
            "error_message",
            "created_at",
        } <= item_columns
        indexes = {
            row[1]
            for row in conn.execute(sa.text("PRAGMA index_list(organization_upload_batches)"))
        }
        assert {
            "ix_organization_upload_batches_organization_id",
            "ix_organization_upload_batches_api_key_id",
            "uq_organization_upload_batches_org_idem",
        } <= indexes
        item_indexes = {
            row[1]
            for row in conn.execute(
                sa.text("PRAGMA index_list(organization_upload_batch_items)")
            )
        }
        assert {
            "ix_organization_upload_batch_items_batch_id",
            "ix_organization_upload_batch_items_document_id",
            "uq_organization_upload_batch_items_batch_index",
        } <= item_indexes

        conn.execute(
            sa.text(
                "INSERT INTO organization_upload_batches"
                " (id, organization_id, api_key_id, idempotency_key, status,"
                " total_count, created_at)"
                " VALUES (:id, :org, :key, 'req-1', 'ACCEPTED', 1, '2026-01-01')"
            ).bindparams(id=batch_id.hex, org=org_id.hex, key=key_id.hex)
        )
        conn.execute(
            sa.text(
                "INSERT INTO organization_upload_batch_items"
                " (id, batch_id, document_id, item_index, patient_email, status, created_at)"
                " VALUES (:id, :batch, :doc, 0, 'anna@clinic.example', 'PENDING',"
                " '2026-01-01')"
            ).bindparams(id=item_id.hex, batch=batch_id.hex, doc=doc_id.hex)
        )
        assert (
            conn.execute(
                sa.text(
                    "SELECT external_id IS NULL FROM organization_upload_batch_items"
                    " WHERE id = :id"
                ).bindparams(id=item_id.hex)
            ).scalar_one()
            == 1
        )
        conn.commit()
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO organization_upload_batches"
                    " (id, organization_id, api_key_id, idempotency_key, status,"
                    " total_count, created_at)"
                    " VALUES (:id, :org, :key, 'req-1', 'ACCEPTED', 1, '2026-01-01')"
                ).bindparams(id=uuid4().hex, org=org_id.hex, key=key_id.hex)
            )
        conn.rollback()
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO organization_upload_batch_items"
                    " (id, batch_id, document_id, item_index, patient_email, status,"
                    " created_at)"
                    " VALUES (:id, :batch, NULL, 0, 'bob@clinic.example', 'PENDING',"
                    " '2026-01-01')"
                ).bindparams(id=uuid4().hex, batch=batch_id.hex)
            )
        conn.rollback()

        with Operations.context(ctx):
            migration.downgrade()
        tables_after = {
            row[0]
            for row in conn.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        assert "organization_upload_batches" not in tables_after
        assert "organization_upload_batch_items" not in tables_after