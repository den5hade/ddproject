from io import BytesIO
from uuid import uuid4

import pytest
from app.domain.access import AuditAction
from app.domain.medical import (
    DocumentNotFoundError,
    DocumentStatus,
    DocumentType,
    OrganizationStatus,
    OrganizationType,
)
from app.domain.organization import (
    BranchStatus,
    InvalidPatientIdentityError,
    OrganizationBranchNotFoundError,
    OrganizationDocumentIdempotencyConflictError,
)
from app.models.account import Account
from app.models.audit_log import AuditLog
from app.models.organization import Organization, OrganizationBranch
from app.services.documents import DocumentService
from app.services.organization_document import OrganizationDocumentService
from app.services.patient import PatientService
from contracts.events import DocumentUploadRequested, OrganizationDocumentSubmitted
from fastapi import UploadFile
from sqlalchemy import select


class FakePublisher:
    def __init__(self):
        self.published = []

    async def publish(self, routing_key: str, event) -> None:
        self.published.append((routing_key, event))


_PDF = b"%PDF-1.7\n" + b"x" * 512


def _upload(name: str = "cbc.pdf") -> UploadFile:
    return UploadFile(
        file=BytesIO(_PDF), filename=name, headers={"content-type": "application/pdf"}
    )


def _document_service(db_session, publisher=None) -> DocumentService:
    return DocumentService(db_session, publisher=publisher)


def _org_document_service(db_session, publisher=None) -> OrganizationDocumentService:
    return OrganizationDocumentService(
        db_session, document_service=_document_service(db_session, publisher)
    )


async def _patient_context(db_session):
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


async def _audit_entries(db_session):
    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == AuditAction.INTEGRATION_DOCUMENT_UPLOADED)
    )
    return list(result.scalars().all())


async def test_create_organization_document_sets_source_columns(db_session):
    context = await _patient_context(db_session)
    service = _document_service(db_session)
    org_id, branch_id = uuid4(), uuid4()

    doc = await service.create_organization_document(
        organization_id=org_id,
        organization_branch_id=branch_id,
        patient_id=context.patient.id,
        medical_record_id=context.medical_record.id,
        document_type=DocumentType.LAB_RESULT,
        provided_document_type="lab_result",
        external_id="ext-9",
        idempotency_key="idem-9",
        title="CBC",
        upload=_upload(),
    )

    assert doc.organization_id == org_id
    assert doc.organization_branch_id == branch_id
    assert doc.external_id == "ext-9"
    assert doc.idempotency_key == "idem-9"
    assert doc.provided_document_type == "lab_result"
    assert doc.uploaded_by_account_id is None
    assert doc.status == DocumentStatus.PENDING


async def test_create_organization_document_skips_free_quota(db_session):
    context = await _patient_context(db_session)
    service = _document_service(db_session)

    for i in range(11):
        await service.create_organization_document(
            organization_id=uuid4(),
            organization_branch_id=None,
            patient_id=context.patient.id,
            medical_record_id=context.medical_record.id,
            document_type=DocumentType.OTHER,
            provided_document_type="other",
            external_id=f"ext-{i}",
            idempotency_key=f"idem-{i}",
            title=None,
            upload=_upload(),
        )

    from app.models.document import Document

    result = await db_session.execute(
        select(Document.id).where(Document.medical_record_id == context.medical_record.id)
    )
    assert len(result.scalars().all()) == 11


async def test_create_organization_document_publishes_pipeline_event(db_session):
    context = await _patient_context(db_session)
    publisher = FakePublisher()
    service = _document_service(db_session, publisher)

    await service.create_organization_document(
        organization_id=uuid4(),
        organization_branch_id=None,
        patient_id=context.patient.id,
        medical_record_id=context.medical_record.id,
        document_type=DocumentType.LAB_RESULT,
        provided_document_type="lab_result",
        external_id=None,
        idempotency_key=None,
        title="CBC",
        upload=_upload(),
    )

    routing_keys = [key for key, _ in publisher.published]
    assert "document.upload.requested" in routing_keys
    event = next(
        e
        for key, e in publisher.published
        if key == "document.upload.requested"
    )
    assert isinstance(event, DocumentUploadRequested)
    assert event.document_type == "lab_result"


async def test_submit_document_creates_document_audit_and_event(db_session):
    org, _ = await _organization(db_session)
    publisher = FakePublisher()
    service = _org_document_service(db_session, publisher)

    result = await service.submit_document(
        organization_id=org.id,
        patient_email="anna@clinic.example",
        document_type=DocumentType.LAB_RESULT,
        external_id="ext-1",
        branch_code=None,
        title="CBC",
        idempotency_key="req-1",
        upload=_upload(),
    )

    assert result.replayed is False
    assert result.patient_id is not None
    assert result.document.organization_id == org.id
    assert result.document.provided_document_type == "lab_result"
    assert (await _audit_entries(db_session))[0].resource_id == result.document.id
    kinds = [key for key, _ in publisher.published]
    assert "organization.document.submitted" in kinds
    event = next(
        e
        for key, e in publisher.published
        if key == "organization.document.submitted"
    )
    assert isinstance(event, OrganizationDocumentSubmitted)
    assert event.organization_id == org.id
    assert event.document_id == result.document.id
    assert event.external_id == "ext-1"
    assert event.document_type == "lab_result"


async def test_submit_replays_by_external_id_without_resubmitting(db_session):
    org, _ = await _organization(db_session)
    publisher = FakePublisher()
    service = _org_document_service(db_session, publisher)

    first = await service.submit_document(
        organization_id=org.id,
        patient_email="anna@clinic.example",
        document_type=DocumentType.OTHER,
        external_id="ext-1",
        branch_code=None,
        title=None,
        idempotency_key=None,
        upload=_upload(),
    )
    assert first.replayed is False

    second = await service.submit_document(
        organization_id=org.id,
        patient_email="anna@clinic.example",
        document_type=DocumentType.OTHER,
        external_id="ext-1",
        branch_code=None,
        title=None,
        idempotency_key=None,
        upload=_upload(),
    )

    assert second.document.id == first.document.id
    assert second.replayed is True
    assert second.patient_id == first.patient_id
    assert len(await _audit_entries(db_session)) == 1
    submitted = [key for key, _ in publisher.published]
    assert submitted.count("organization.document.submitted") == 1


async def test_submit_replays_by_idempotency_key(db_session):
    org, _ = await _organization(db_session)
    service = _org_document_service(db_session)

    first = await service.submit_document(
        organization_id=org.id,
        patient_email="anna@clinic.example",
        document_type=DocumentType.OTHER,
        external_id=None,
        branch_code=None,
        title=None,
        idempotency_key="req-1",
        upload=_upload(),
    )

    second = await service.submit_document(
        organization_id=org.id,
        patient_email="anna@clinic.example",
        document_type=DocumentType.OTHER,
        external_id=None,
        branch_code=None,
        title=None,
        idempotency_key="req-1",
        upload=_upload(),
    )

    assert second.document.id == first.document.id
    assert second.replayed is True


async def test_submit_conflicts_when_keys_map_to_different_documents(db_session):
    org, _ = await _organization(db_session)
    service = _org_document_service(db_session)

    await service.submit_document(
        organization_id=org.id,
        patient_email="anna@clinic.example",
        document_type=DocumentType.OTHER,
        external_id="ext-a",
        branch_code=None,
        title=None,
        idempotency_key=None,
        upload=_upload(),
    )
    await service.submit_document(
        organization_id=org.id,
        patient_email="anna@clinic.example",
        document_type=DocumentType.OTHER,
        external_id="ext-b",
        branch_code=None,
        title=None,
        idempotency_key="req-b",
        upload=_upload(),
    )

    with pytest.raises(OrganizationDocumentIdempotencyConflictError):
        await service.submit_document(
            organization_id=org.id,
            patient_email="anna@clinic.example",
            document_type=DocumentType.OTHER,
            external_id="ext-a",
            branch_code=None,
            title=None,
            idempotency_key="req-b",
            upload=_upload(),
        )


async def test_submit_resolves_active_branch(db_session):
    org, branch = await _organization(db_session)
    service = _org_document_service(db_session)

    result = await service.submit_document(
        organization_id=org.id,
        patient_email="anna@clinic.example",
        document_type=DocumentType.OTHER,
        external_id="ext-1",
        branch_code=branch.code,
        title=None,
        idempotency_key=None,
        upload=_upload(),
    )

    assert result.document.organization_branch_id == branch.id


async def test_submit_rejects_unknown_or_inactive_branch(db_session):
    org, branch = await _organization(db_session, branch_status=BranchStatus.INACTIVE)
    service = _org_document_service(db_session)

    with pytest.raises(OrganizationBranchNotFoundError):
        await service.submit_document(
            organization_id=org.id,
            patient_email="anna@clinic.example",
            document_type=DocumentType.OTHER,
            external_id="ext-1",
            branch_code=branch.code,
            title=None,
            idempotency_key="req-1",
            upload=_upload(),
        )

    with pytest.raises(OrganizationBranchNotFoundError):
        await service.submit_document(
            organization_id=org.id,
            patient_email="anna@clinic.example",
            document_type=DocumentType.OTHER,
            external_id="ext-2",
            branch_code="no-such-branch",
            title=None,
            idempotency_key="req-2",
            upload=_upload(),
        )


async def test_submit_rejects_phone_identity_even_when_email_expected(db_session):
    org, _ = await _organization(db_session)
    service = _org_document_service(db_session)

    with pytest.raises(InvalidPatientIdentityError):
        await service.submit_document(
            organization_id=org.id,
            patient_email="+79991234567",
            document_type=DocumentType.OTHER,
            external_id="ext-1",
            branch_code=None,
            title=None,
            idempotency_key="req-1",
            upload=_upload(),
        )


async def test_get_document_is_organization_scoped(db_session):
    org_a, _ = await _organization(db_session)
    org_b, _ = await _organization(db_session)
    service = _org_document_service(db_session)

    result = await service.submit_document(
        organization_id=org_a.id,
        patient_email="anna@clinic.example",
        document_type=DocumentType.OTHER,
        external_id="ext-1",
        branch_code=None,
        title=None,
        idempotency_key=None,
        upload=_upload(),
    )

    assert (await service.get_document(org_a.id, result.document.id)).id == result.document.id

    with pytest.raises(DocumentNotFoundError):
        await service.get_document(org_b.id, result.document.id)