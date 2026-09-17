from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.domain.medical import (
    DocumentStatus,
    OrganizationStatus,
    OrganizationType,
)
from app.domain.organization import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
from app.models.account import Account
from app.models.document import Document, DocumentVersion
from app.models.medical_record import MedicalRecord
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.patient import Patient
from app.models.person import Person
from app.models.processing_job import DocumentProcessingJob
from app.services.documents import DocumentService
from app.services.notifications import (
    NotificationService,
    notification_body,
    notification_subject,
)
from contracts.events import (
    DocumentAnalysisCompleted,
    DocumentProcessingFailed,
    NotificationRequested,
)
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[4]


class FakePublisher:
    def __init__(self, exploding: bool = False):
        self.published = []
        self.exploding = exploding

    async def publish(self, routing_key: str, event) -> None:
        if self.exploding:
            raise RuntimeError("broker connection lost")
        self.published.append((routing_key, event))


async def _account(db_session) -> Account:
    person = Person()
    db_session.add(person)
    await db_session.flush()
    account = Account(id=uuid4(), email="anna@clinic.example", person_id=person.id)
    db_session.add(account)
    await db_session.flush()
    return account


async def _org_document(
    db_session, account: Account, organization=None
) -> tuple:
    patient = Patient(person_id=account.person_id)
    db_session.add(patient)
    await db_session.flush()
    record = MedicalRecord(patient_id=patient.id)
    db_session.add(record)
    await db_session.flush()
    organization_id = organization.id if organization is not None else None
    document = Document(
        medical_record_id=record.id,
        original_filename="scan.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        status=DocumentStatus.PENDING,
        uploaded_by_account_id=account.id,
        organization_id=organization_id,
    )
    db_session.add(document)
    await db_session.flush()
    version = DocumentVersion(document_id=document.id, version=1)
    db_session.add(version)
    await db_session.flush()
    job = DocumentProcessingJob(
        document_id=document.id,
        document_version_id=version.id,
        job_type="pdf_conversion",
    )
    db_session.add(job)
    await db_session.commit()
    return document, version, job, patient


async def _notification(db_session, account) -> Notification:
    notification = Notification(
        account_id=account.id,
        type=NotificationType.DOCUMENT_PROCESSED,
        title="Document processed — City Clinic",
        template="City Clinic processed your medical document.",
        resource_id=uuid4(),
    )
    db_session.add(notification)
    await db_session.commit()
    return notification


async def test_create_for_document_persists_pending_and_publishes(db_session):
    account = await _account(db_session)
    org = Organization(
        name="City Clinic", type=OrganizationType.CLINIC, status=OrganizationStatus.ACTIVE
    )
    db_session.add(org)
    await db_session.flush()
    document, version, _job, _patient = await _org_document(db_session, account, org)

    publisher = FakePublisher()
    service = NotificationService(db_session, publisher)
    notification = await service.create_for_document(
        account_id=account.id,
        organization_id=org.id,
        notification_type=NotificationType.DOCUMENT_PROCESSED,
        org_name=org.name,
        to_email="anna@clinic.example",
        secure_link=f"http://localhost:5173/documents/{document.id}",
        resource_id=document.id,
    )

    refreshed = await db_session.get(Notification, notification.id)
    assert refreshed is not None
    assert refreshed.status is NotificationStatus.PENDING
    assert refreshed.type is NotificationType.DOCUMENT_PROCESSED
    assert refreshed.channel is NotificationChannel.EMAIL
    assert refreshed.account_id == account.id
    assert refreshed.organization_id == org.id
    assert refreshed.resource_type == "document"
    assert refreshed.resource_id == document.id
    assert "City Clinic" in refreshed.title
    assert "City Clinic" in refreshed.template

    routing_key, event = publisher.published[0]
    assert routing_key == "notification.requested"
    assert isinstance(event, NotificationRequested)
    assert event.notification_id == notification.id
    assert event.account_id == account.id
    assert event.channel == "email"
    assert event.to == "anna@clinic.example"
    assert event.subject == refreshed.title
    assert event.body == refreshed.template


async def test_create_for_document_templates_have_no_medical_data():
    document_id = uuid4()
    subject = notification_subject(NotificationType.DOCUMENT_PROCESSED, "City Clinic")
    body = notification_body(
        NotificationType.DOCUMENT_PROCESSED,
        "City Clinic",
        "http://localhost:5173/documents/seg",
        document_id,
    )

    assert "City Clinic" in subject
    assert "City Clinic" in body
    assert str(document_id) in body
    for banned in ("wbc", "6.4", "diagnosis", "scan.pdf", "canonical", "patient_id"):
        assert banned.lower() not in body.lower()


async def test_create_for_document_marks_failed_when_publish_fails(db_session):
    account = await _account(db_session)
    org = Organization(
        name="City Clinic", type=OrganizationType.CLINIC, status=OrganizationStatus.ACTIVE
    )
    db_session.add(org)
    await db_session.flush()
    document, _version, _job, _patient = await _org_document(db_session, account, org)

    publisher = FakePublisher(exploding=True)
    service = NotificationService(db_session, publisher)
    notification = await service.create_for_document(
        account_id=account.id,
        organization_id=org.id,
        notification_type=NotificationType.DOCUMENT_PROCESSED,
        org_name=org.name,
        to_email="anna@clinic.example",
        secure_link="http://localhost:5173/documents/x",
        resource_id=document.id,
    )

    refreshed = await db_session.get(Notification, notification.id)
    assert refreshed.status is NotificationStatus.FAILED
    assert refreshed.error_message == "publish failed"


async def test_create_for_document_marks_failed_without_publisher(db_session):
    account = await _account(db_session)
    org = Organization(
        name="City Clinic", type=OrganizationType.CLINIC, status=OrganizationStatus.ACTIVE
    )
    db_session.add(org)
    await db_session.flush()
    document, _version, _job, _patient = await _org_document(db_session, account, org)

    service = NotificationService(db_session, None)
    notification = await service.create_for_document(
        account_id=account.id,
        organization_id=org.id,
        notification_type=NotificationType.DOCUMENT_PROCESSED,
        org_name=org.name,
        to_email="anna@clinic.example",
        secure_link="http://localhost:5173/documents/x",
        resource_id=document.id,
    )

    refreshed = await db_session.get(Notification, notification.id)
    assert refreshed.status is NotificationStatus.FAILED
    assert refreshed.error_message == "publish failed"


async def test_mark_delivered_sets_sent(db_session):
    account = await _account(db_session)
    notification = await _notification(db_session, account)

    await NotificationService(db_session, None).mark_delivered(notification.id)

    refreshed = await db_session.get(Notification, notification.id)
    assert refreshed.status is NotificationStatus.SENT
    assert refreshed.sent_at is not None


async def test_mark_failed_sets_failed_with_error(db_session):
    account = await _account(db_session)
    notification = await _notification(db_session, account)

    await NotificationService(db_session, None).mark_failed(notification.id, "smtp down")

    refreshed = await db_session.get(Notification, notification.id)
    assert refreshed.status is NotificationStatus.FAILED
    assert refreshed.error_message == "smtp down"


async def test_mark_delivered_missing_id_is_noop(db_session):
    await NotificationService(db_session, None).mark_delivered(uuid4())
    remaining = await db_session.scalar(select(Notification))
    assert remaining is None


async def test_org_document_analysis_completed_creates_notification(db_session):
    account = await _account(db_session)
    org = Organization(
        name="City Clinic", type=OrganizationType.CLINIC, status=OrganizationStatus.ACTIVE
    )
    db_session.add(org)
    await db_session.flush()
    document, version, _job, patient = await _org_document(db_session, account, org)

    publisher = FakePublisher()
    await DocumentService(db_session, publisher=publisher).on_document_analysis_completed(
        DocumentAnalysisCompleted(
            event_id=uuid4(),
            document_id=document.id,
            document_version_id=version.id,
            patient_id=patient.id,
            extraction_id=uuid4(),
            schema_name="cbc",
            status="succeeded",
            confidence=0.98,
            data={"wbc": "6.4"},
        )
    )

    notifications = list(
        (await db_session.execute(select(Notification))).scalars().all()
    )
    assert len(notifications) == 1
    assert notifications[0].type is NotificationType.DOCUMENT_PROCESSED
    assert notifications[0].account_id == account.id
    assert notifications[0].organization_id == org.id
    assert "wbc" not in notifications[0].template.lower()
    assert "6.4" not in notifications[0].template.lower()

    kinds = [key for key, _ in publisher.published]
    assert "notification.requested" in kinds


async def test_org_document_processing_failed_creates_notification(db_session):
    account = await _account(db_session)
    org = Organization(
        name="City Clinic", type=OrganizationType.CLINIC, status=OrganizationStatus.ACTIVE
    )
    db_session.add(org)
    await db_session.flush()
    document, version, _job, patient = await _org_document(db_session, account, org)

    await DocumentService(db_session, publisher=FakePublisher()).on_document_processing_failed(
        DocumentProcessingFailed(
            event_id=uuid4(),
            document_id=document.id,
            document_version_id=version.id,
            patient_id=patient.id,
            job_type="pdf_conversion",
            error_code="corrupt_file",
            error_message="broken pdf",
        )
    )

    notifications = list(
        (await db_session.execute(select(Notification))).scalars().all()
    )
    assert len(notifications) == 1
    assert notifications[0].type is NotificationType.DOCUMENT_PROCESSING_FAILED
    assert notifications[0].account_id == account.id


async def test_non_org_document_creates_no_notification(db_session):
    account = await _account(db_session)
    patient = Patient(person_id=account.person_id)
    db_session.add(patient)
    await db_session.flush()
    record = MedicalRecord(patient_id=patient.id)
    db_session.add(record)
    await db_session.flush()
    document = Document(
        medical_record_id=record.id,
        original_filename="scan.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        status=DocumentStatus.PENDING,
        uploaded_by_account_id=account.id,
    )
    db_session.add(document)
    await db_session.flush()
    version = DocumentVersion(document_id=document.id, version=1)
    db_session.add(version)
    await db_session.flush()
    job = DocumentProcessingJob(
        document_id=document.id, document_version_id=version.id, job_type="pdf_conversion"
    )
    db_session.add(job)
    await db_session.commit()

    await DocumentService(db_session, publisher=FakePublisher()).on_document_analysis_completed(
        DocumentAnalysisCompleted(
            event_id=uuid4(),
            document_id=document.id,
            document_version_id=version.id,
            patient_id=patient.id,
            extraction_id=uuid4(),
            schema_name="cbc",
            status="succeeded",
            confidence=0.98,
            data={"wbc": "6.4"},
        )
    )

    assert await db_session.scalar(select(Notification)) is None


async def test_notification_failure_does_not_break_pipeline(db_session):
    account = await _account(db_session)
    org = Organization(
        name="City Clinic", type=OrganizationType.CLINIC, status=OrganizationStatus.ACTIVE
    )
    db_session.add(org)
    await db_session.flush()
    document, version, _job, patient = await _org_document(db_session, account, org)

    exploding = FakePublisher(exploding=True)
    service = DocumentService(db_session, publisher=exploding)
    await service.on_document_analysis_completed(
        DocumentAnalysisCompleted(
            event_id=uuid4(),
            document_id=document.id,
            document_version_id=version.id,
            patient_id=patient.id,
            extraction_id=uuid4(),
            schema_name="cbc",
            status="succeeded",
            confidence=0.98,
            data={"wbc": "6.4"},
        )
    )

    assert (await db_session.get(Document, document.id)).status == DocumentStatus.COMPLETED
    notifications = list(
        (await db_session.execute(select(Notification))).scalars().all()
    )
    assert len(notifications) == 1
    assert notifications[0].status is NotificationStatus.FAILED


async def test_notification_missing_org_is_skipped(db_session):
    account = await _account(db_session)
    document, version, _job, patient = await _org_document(db_session, account, None)
    document.organization_id = uuid4()
    await db_session.commit()

    await DocumentService(db_session, publisher=FakePublisher()).on_document_analysis_completed(
        DocumentAnalysisCompleted(
            event_id=uuid4(),
            document_id=document.id,
            document_version_id=version.id,
            patient_id=patient.id,
            extraction_id=uuid4(),
            schema_name="cbc",
            status="succeeded",
            confidence=0.98,
            data={"wbc": "6.4"},
        )
    )
    assert (await db_session.get(Document, document.id)).status == DocumentStatus.COMPLETED
    assert await db_session.scalar(select(Notification)) is None


def _load_migration_0015():
    path = REPO_ROOT / "migrations/alembic/versions/0015_notifications.py"
    spec = spec_from_file_location("migration_0015", path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_0015_revision_wiring() -> None:
    migration = _load_migration_0015()
    assert migration.revision == "0015"
    assert migration.down_revision == "0013"


def test_migration_0015_upgrade_downgrade_round_trip() -> None:
    migration = _load_migration_0015()
    engine = sa.create_engine("sqlite://")

    @sa.event.listens_for(engine, "connect")
    def _set_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    account_id, org_id, notify_id = (uuid4() for _ in range(3))
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                CREATE TABLE accounts (
                    id VARCHAR(32) PRIMARY KEY
                )
                """
            )
        )
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
            sa.text("INSERT INTO accounts (id) VALUES (:id)").bindparams(
                id=account_id.hex
            )
        )
        conn.execute(
            sa.text("INSERT INTO organizations (id, name) VALUES (:id, 'City Clinic')").bindparams(
                id=org_id.hex
            )
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
        assert "notifications" in tables
        columns = {
            row[1] for row in conn.execute(sa.text("PRAGMA table_info(notifications)"))
        }
        assert {
            "id",
            "account_id",
            "organization_id",
            "type",
            "channel",
            "status",
            "title",
            "template",
            "resource_type",
            "resource_id",
            "error_message",
            "sent_at",
            "read_at",
            "created_at",
        } <= columns
        indexes = {row[1] for row in conn.execute(sa.text("PRAGMA index_list(notifications)"))}
        assert {
            "ix_notifications_account_id",
            "ix_notifications_organization_id",
            "ix_notifications_created_at",
        } <= indexes

        conn.execute(
            sa.text(
                "INSERT INTO notifications"
                " (id, account_id, organization_id, type, channel, status,"
                " title, template, resource_type, resource_id, created_at)"
                " VALUES (:id, :account, :org, 'document_processed', 'email',"
                " 'PENDING', 'Document processed — City Clinic',"
                " 'City Clinic processed your medical document.', 'document',"
                " :resource, '2026-01-01')"
            ).bindparams(
                id=notify_id.hex,
                account=account_id.hex,
                org=org_id.hex,
                resource=uuid4().hex,
            )
        )
        conn.commit()
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO notifications"
                    " (id, account_id, organization_id, type, channel, status,"
                    " title, template, resource_type, resource_id, created_at)"
                    " VALUES (:id, 'no-such-account', NULL, 'document_processed',"
                    " 'email', 'PENDING', 't', 'b', 'document', :resource,"
                    " '2026-01-01')"
                ).bindparams(id=uuid4().hex, resource=uuid4().hex)
            )
        conn.rollback()
        conn.execute(
            sa.text("DELETE FROM notifications WHERE id = :id").bindparams(
                id=notify_id.hex
            )
        )
        conn.execute(
            sa.text("DELETE FROM organizations WHERE id = :id").bindparams(id=org_id.hex)
        )
        conn.commit()
        with Operations.context(ctx):
            migration.downgrade()
        tables_after = {
            row[0]
            for row in conn.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        assert "notifications" not in tables_after