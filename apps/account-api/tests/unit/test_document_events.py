from uuid import uuid4

from app.domain.medical import (
    DocumentStatus,
    ExtractionStatus,
    ProcessingJobStatus,
    ProcessingJobType,
)
from app.models.account import Account
from app.models.document import Document, DocumentVersion
from app.models.extraction import DocumentExtraction
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.person import Person
from app.models.processing_job import DocumentProcessingJob
from app.services.documents import DocumentService
from contracts.events import (
    DocumentAnalysisCompleted,
    DocumentConverted,
    DocumentProcessingFailed,
    DocumentStored,
)
from sqlalchemy import select


class FakePublisher:
    def __init__(self):
        self.published = []

    async def publish(self, routing_key: str, event) -> None:
        self.published.append((routing_key, event))


async def _owned_document(db_session, account_id):
    person = Person()
    db_session.add(person)
    await db_session.flush()
    patient = Patient(person_id=person.id)
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
        uploaded_by_account_id=account_id,
    )
    db_session.add(document)
    await db_session.flush()
    version = DocumentVersion(document_id=document.id, version=1)
    db_session.add(version)
    await db_session.flush()
    job = DocumentProcessingJob(
        document_id=document.id,
        document_version_id=version.id,
        job_type=ProcessingJobType.PDF_CONVERSION,
    )
    db_session.add(job)
    await db_session.commit()
    return document, version, job, patient


async def test_on_document_stored_updates_keys_and_status(db_session):
    account = Account(id=uuid4())
    db_session.add(account)
    await db_session.commit()
    document, version, _job, patient = await _owned_document(db_session, account.id)

    publisher = FakePublisher()
    service = DocumentService(db_session, publisher=publisher)
    await service.on_document_stored(
        DocumentStored(
            event_id=uuid4(),
            document_id=document.id,
            document_version_id=version.id,
            patient_id=patient.id,
            storage_key="tenants/t/patients/p/documents/d/versions/v/original.pdf",
            mime_type="application/pdf",
            size_bytes=2048,
            checksum="sha256:abc123",
        )
    )

    refreshed_version = await db_session.scalar(
        select(DocumentVersion).where(DocumentVersion.id == version.id)
    )
    refreshed_document = await db_session.get(Document, document.id)
    assert refreshed_version.s3_key.endswith("original.pdf")
    assert refreshed_version.checksum == "sha256:abc123"
    assert refreshed_document.status == DocumentStatus.PROCESSING
    assert refreshed_document.size_bytes == 2048

    assert len(publisher.published) == 1
    routing_key, event = publisher.published[0]
    assert routing_key == "document.uploaded"
    assert event.storage_key == refreshed_version.s3_key


async def test_on_document_stored_does_not_republish_when_already_stored(db_session):
    account = Account(id=uuid4())
    db_session.add(account)
    await db_session.commit()
    document, version, _job, patient = await _owned_document(db_session, account.id)
    version.checksum = "sha256:first"
    await db_session.commit()

    publisher = FakePublisher()
    service = DocumentService(db_session, publisher=publisher)
    await service.on_document_stored(
        DocumentStored(
            event_id=uuid4(),
            document_id=document.id,
            document_version_id=version.id,
            patient_id=patient.id,
            storage_key="k",
            mime_type="application/pdf",
            size_bytes=1,
            checksum="sha256:second",
        )
    )
    assert publisher.published == []


async def test_on_document_converted_marks_job_succeeded(db_session):
    account = Account(id=uuid4())
    db_session.add(account)
    await db_session.commit()
    document, version, job, patient = await _owned_document(db_session, account.id)

    service = DocumentService(db_session)
    await service.on_document_converted(
        DocumentConverted(
            event_id=uuid4(),
            document_id=document.id,
            document_version_id=version.id,
            patient_id=patient.id,
            output_storage_key="converted/md/doc.md",
        )
    )

    refreshed = await db_session.get(DocumentProcessingJob, job.id)
    assert refreshed.status == ProcessingJobStatus.SUCCEEDED
    assert refreshed.finished_at is not None


async def test_on_document_analysis_completed_creates_extraction(db_session):
    account = Account(id=uuid4())
    db_session.add(account)
    await db_session.commit()
    document, version, _job, patient = await _owned_document(db_session, account.id)

    extraction_id = uuid4()
    service = DocumentService(db_session)
    await service.on_document_analysis_completed(
        DocumentAnalysisCompleted(
            event_id=uuid4(),
            document_id=document.id,
            document_version_id=version.id,
            patient_id=patient.id,
            extraction_id=extraction_id,
            schema_name="cbc",
            status="succeeded",
            confidence=0.98,
            data={"wbc": "6.4"},
        )
    )

    extraction = await db_session.get(DocumentExtraction, extraction_id)
    assert extraction is not None
    assert extraction.status == ExtractionStatus.SUCCEEDED
    assert extraction.confidence == 0.98
    assert extraction.data == {"wbc": "6.4"}
    assert (await db_session.get(Document, document.id)).status == DocumentStatus.COMPLETED


async def test_on_document_analysis_completed_failure_marks_document_failed(db_session):
    account = Account(id=uuid4())
    db_session.add(account)
    await db_session.commit()
    document, version, _job, patient = await _owned_document(db_session, account.id)

    service = DocumentService(db_session)
    await service.on_document_analysis_completed(
        DocumentAnalysisCompleted(
            event_id=uuid4(),
            document_id=document.id,
            document_version_id=version.id,
            patient_id=patient.id,
            extraction_id=uuid4(),
            schema_name="cbc",
            status="failed",
            confidence=None,
            data=None,
        )
    )

    assert (await db_session.get(Document, document.id)).status == DocumentStatus.FAILED


async def test_on_document_processing_failed_marks_document_and_job(db_session):
    account = Account(id=uuid4())
    db_session.add(account)
    await db_session.commit()
    document, version, job, patient = await _owned_document(db_session, account.id)

    service = DocumentService(db_session)
    await service.on_document_processing_failed(
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

    refreshed_job = await db_session.get(DocumentProcessingJob, job.id)
    assert refreshed_job.status == ProcessingJobStatus.FAILED
    assert refreshed_job.error_code == "corrupt_file"
    assert (await db_session.get(Document, document.id)).status == DocumentStatus.FAILED


async def test_event_for_unknown_version_is_ignored(db_session):
    account = Account(id=uuid4())
    db_session.add(account)
    await db_session.commit()
    service = DocumentService(db_session, publisher=FakePublisher())
    document_id = uuid4()

    await service.on_document_stored(
        DocumentStored(
            event_id=uuid4(),
            document_id=document_id,
            document_version_id=uuid4(),
            patient_id=uuid4(),
            storage_key="k",
            mime_type="application/pdf",
            size_bytes=1,
            checksum="sha256:x",
        )
    )

    assert await db_session.get(Document, document_id) is None