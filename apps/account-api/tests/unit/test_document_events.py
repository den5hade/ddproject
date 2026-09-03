import asyncio
import logging
from uuid import uuid4

import pytest
from app.consumers import document_events
from app.consumers.document_events import run_consumer
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


async def test_analysis_completed_persists_enriched_canonical_and_keys(db_session):
    """Phase F: enriched DocumentAnalysisCompleted.data (canonical + keys)
    round-trips into the document_extractions.data JSON column."""
    account = Account(id=uuid4())
    db_session.add(account)
    await db_session.commit()
    document, version, _job, patient = await _owned_document(db_session, account.id)

    canonical = {"type": "laboratory", "fields": {"wbc": "6.4"}}
    canonical_key = (
        f"tenants/default/patients/{patient.id}/documents/{document.id}"
        f"/versions/{version.id}/canonical.json"
    )
    structured_key = canonical_key.replace("canonical.json", "structured.md")

    extraction_id = uuid4()
    service = DocumentService(db_session)
    await service.on_document_analysis_completed(
        DocumentAnalysisCompleted(
            event_id=uuid4(),
            document_id=document.id,
            document_version_id=version.id,
            patient_id=patient.id,
            extraction_id=extraction_id,
            schema_name="laboratory",
            schema_version="1.0.0",
            status="succeeded",
            confidence=1.0,
            data={**canonical, "canonical_key": canonical_key, "structured_key": structured_key},
        )
    )

    extraction = await db_session.get(DocumentExtraction, extraction_id)
    assert extraction is not None
    assert extraction.schema_name == "laboratory"
    assert extraction.schema_version == "1.0.0"
    assert extraction.status == ExtractionStatus.SUCCEEDED
    assert extraction.data["type"] == "laboratory"
    assert extraction.data["fields"] == {"wbc": "6.4"}
    assert extraction.data["canonical_key"] == canonical_key
    assert extraction.data["structured_key"] == structured_key
    assert (await db_session.get(Document, document.id)).status == DocumentStatus.COMPLETED


async def test_analysis_completed_persists_document_date(db_session):
    """document_date from the canonical payload is persisted onto the document."""
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
            schema_name="laboratory",
            status="succeeded",
            confidence=1.0,
            data={"document_date": "2026-09-03", "fields": {"wbc": "6.4"}},
        )
    )

    refreshed = await db_session.get(Document, document.id)
    assert refreshed.document_date is not None
    assert refreshed.document_date.strftime("%Y-%m-%d") == "2026-09-03"


async def test_analysis_completed_keeps_document_date_null_when_absent(db_session):
    """A missing/unparseable document_date leaves the column null (Новые bucket)."""
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
            schema_name="generic",
            status="succeeded",
            confidence=1.0,
            data={"fields": {"x": "y"}},
        )
    )

    refreshed = await db_session.get(Document, document.id)
    assert refreshed.document_date is None


async def test_analysis_completed_creates_extraction_when_id_is_new(db_session):
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
            schema_name="generic",
            schema_version="1.0.0",
            status="succeeded",
            confidence=1.0,
            data={"type": "generic", "canonical_key": "k", "structured_key": "s"},
        )
    )

    extraction = await db_session.scalar(
        select(DocumentExtraction).where(DocumentExtraction.schema_name == "generic")
    )
    assert extraction is not None
    assert extraction.data["type"] == "generic"
    assert extraction.data["canonical_key"] == "k"
    assert extraction.data["structured_key"] == "s"


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


# --------------------------------------------------------------- F6 consumer


class _ProcessCM:
    def __init__(self, msg):
        self._msg = msg

    async def __aenter__(self):
        return self._msg

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self._msg.rejected = True
            return False
        self._msg.acked = True
        return True


class FakeMessage:
    def __init__(self, type_="UnknownEvent", body=b""):
        self.type = type_
        self.body = body
        self.message_id = str(uuid4())
        self.delivery_tag = 1
        self.acked = False
        self.rejected = False

    def process(self):
        return _ProcessCM(self)


class FakeConsumer:
    def __init__(self, start_error=None, iterator_error=None, messages=()):
        self.start_error = start_error
        self.iterator_error = iterator_error
        self.messages_list = list(messages)
        self.started = 0
        self.closed = 0

    async def start(self):
        self.started += 1
        if self.start_error is not None:
            raise self.start_error

    async def messages(self):
        for message in self.messages_list:
            yield message
        if self.iterator_error is not None:
            raise self.iterator_error

    async def close(self):
        self.closed += 1


class StopTest(Exception):
    pass


def _scripted_factory(consumers):
    queue = list(consumers)
    made = []

    def factory():
        if not queue:
            raise StopTest()
        consumer = queue.pop(0)
        made.append(consumer)
        return consumer

    return factory, made


async def test_start_failure_retries_with_fresh_consumer():
    failing = FakeConsumer(start_error=ConnectionError("broker down"))
    healthy = FakeConsumer()
    factory, made = _scripted_factory([failing, healthy])
    recorded = []

    async def record_sleep(delay):
        recorded.append(delay)

    with pytest.raises(StopTest):
        await run_consumer(factory, record_sleep)

    assert len(made) == 2
    assert made[0].started == 1
    assert healthy.started == 1
    assert recorded == [document_events._BACKOFF_INITIAL_SECONDS]


async def test_disconnect_recovers_and_resets_backoff():
    handled_message = FakeMessage("UnknownEvent")
    flaky_after_success = FakeConsumer(
        messages=[handled_message],
        iterator_error=RuntimeError("connection lost"),
    )
    flaky_immediately = FakeConsumer(iterator_error=RuntimeError("still down"))
    healthy = FakeConsumer()
    factory, made = _scripted_factory([flaky_after_success, flaky_immediately, healthy])
    recorded = []

    async def record_sleep(delay):
        recorded.append(delay)

    with pytest.raises(StopTest):
        await run_consumer(factory, record_sleep)

    assert handled_message.acked is True
    assert flaky_after_success.closed == 1
    assert len(made) == 3
    assert recorded[0] == document_events._BACKOFF_INITIAL_SECONDS
    assert document_events._BACKOFF_INITIAL_SECONDS * 2 <= recorded[1] < (
        document_events._BACKOFF_MAX_SECONDS
    )


async def test_handler_failure_does_not_kill_loop(monkeypatch, caplog):
    bad = FakeMessage("DocumentStored", body=b"{}")
    good = FakeMessage("UnknownEvent")
    consumer = FakeConsumer(messages=[bad, good])
    factory, made = _scripted_factory([consumer])
    handled = []

    async def fake_handle(message):
        handled.append(message)
        async with message.process():
            if message is bad:
                raise ValueError("boom")

    monkeypatch.setattr(document_events, "_handle", fake_handle)

    with caplog.at_level(logging.ERROR, logger="account_api.consumer"), pytest.raises(StopTest):
        await run_consumer(factory, None)

    assert handled == [bad, good]
    assert bad.rejected is True
    assert good.acked is True
    assert made[0].closed == 1
    assert any("document_event_handler_failed" in r.getMessage() for r in caplog.records)


async def test_malformed_events_dropped_cleanly(caplog):
    junk_type = FakeMessage("NoSuchEvent")
    junk_body = FakeMessage("DocumentStored", body=b"{not json")
    consumer = FakeConsumer(messages=[junk_type, junk_body])
    factory, _made = _scripted_factory([consumer])

    with caplog.at_level(logging.WARNING, logger="account_api.consumer"), pytest.raises(StopTest):
        await run_consumer(factory, None)

    assert junk_type.acked and junk_body.acked
    warnings_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "event_unsupported" in warnings_text or "event_invalid" in warnings_text


async def test_cancellation_propagates_and_closes_consumer():
    consumer = FakeConsumer()

    async def endless_messages():
        yield FakeMessage("UnknownEvent")
        await asyncio.Event().wait()

    consumer.messages = endless_messages
    factory, _made = _scripted_factory([consumer])

    task = asyncio.create_task(run_consumer(factory, None))
    for _ in range(10):
        await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert consumer.closed >= 1