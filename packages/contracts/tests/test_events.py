from uuid import uuid4

from contracts.events import (
    DocumentProcessingFailed,
    DocumentStored,
    DocumentUploadRequested,
)


def _base_kwargs(**overrides):
    kwargs = {
        "document_id": uuid4(),
        "document_version_id": uuid4(),
        "patient_id": uuid4(),
    }
    kwargs.update(overrides)
    return kwargs


def test_document_stored_round_trip():
    event = DocumentStored(
        event_id=uuid4(),
        **_base_kwargs(),
        storage_key="tenants/t/patients/p/documents/d/versions/v/original.pdf",
        mime_type="application/pdf",
        size_bytes=2048,
        checksum="sha256:abc",
    )
    parsed = DocumentStored.model_validate_json(event.model_dump_json())
    assert parsed == event
    assert parsed.storage_key.endswith("original.pdf")
    assert parsed.schema_version == 1


def test_document_upload_requested_round_trip():
    event = DocumentUploadRequested(
        event_id=uuid4(),
        **_base_kwargs(),
        tenant_id="acme",
        medical_record_id=uuid4(),
        temp_path="/app/uploads/uuid.upload",
        original_filename="cbc.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
    )
    parsed = DocumentUploadRequested.model_validate_json(event.model_dump_json())
    assert parsed == event
    assert parsed.tenant_id == "acme"


def test_document_processing_failed_defaults():
    event = DocumentProcessingFailed(
        event_id=uuid4(), **_base_kwargs(), job_type="pdf_conversion"
    )
    assert event.error_code is None
    assert event.error_message is None
    parsed = DocumentProcessingFailed.model_validate_json(event.model_dump_json())
    assert parsed.error_code is None


def test_schema_version_defaults_to_one():
    event = DocumentStored(
        event_id=uuid4(),
        **_base_kwargs(),
        storage_key="k",
        mime_type="application/pdf",
        size_bytes=1,
        checksum="sha256:x",
    )
    assert event.schema_version == 1