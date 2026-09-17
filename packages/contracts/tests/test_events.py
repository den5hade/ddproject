from uuid import uuid4

from contracts.events import (
    DocumentAnalysisRequested,
    DocumentConversionRequested,
    DocumentConverted,
    DocumentProcessingFailed,
    DocumentStored,
    DocumentUploaded,
    DocumentUploadRequested,
    NotificationDelivered,
    NotificationRequested,
    OrganizationBatchCompleted,
    OrganizationBatchCreated,
    OrganizationDocumentSubmitted,
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
        original_filename="cbc.pdf",
        document_type="lab_result",
    )
    parsed = DocumentStored.model_validate_json(event.model_dump_json())
    assert parsed == event
    assert parsed.storage_key.endswith("original.pdf")
    assert parsed.schema_version == 1
    assert parsed.original_filename == "cbc.pdf"
    assert parsed.document_type == "lab_result"


def test_document_stored_source_defaults():
    event = DocumentStored(
        event_id=uuid4(),
        **_base_kwargs(),
        storage_key="k",
        mime_type="application/pdf",
        size_bytes=1,
        checksum="sha256:x",
    )
    assert event.original_filename == ""
    assert event.document_type == "other"


def test_document_uploaded_round_trip():
    event = DocumentUploaded(
        event_id=uuid4(),
        **_base_kwargs(),
        storage_key="tenants/t/patients/p/documents/d/versions/v/original.pdf",
        original_filename="cbc.pdf",
        mime_type="application/pdf",
        sha256="abc123",
        document_type="lab_result",
    )
    parsed = DocumentUploaded.model_validate_json(event.model_dump_json())
    assert parsed == event
    assert parsed.sha256 == "abc123"
    assert parsed.document_type == "lab_result"


def test_document_converted_round_trip():
    event = DocumentConverted(
        event_id=uuid4(),
        **_base_kwargs(),
        output_storage_key="tenants/t/patients/p/documents/d/versions/v/marker.md",
        original_filename="cbc.pdf",
        mime_type="application/pdf",
        sha256="abc123",
        document_type="lab_result",
    )
    parsed = DocumentConverted.model_validate_json(event.model_dump_json())
    assert parsed == event
    assert parsed.output_storage_key.endswith("marker.md")
    assert parsed.original_filename == "cbc.pdf"
    assert parsed.document_type == "lab_result"


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
        document_type="lab_result",
    )
    parsed = DocumentUploadRequested.model_validate_json(event.model_dump_json())
    assert parsed == event
    assert parsed.tenant_id == "acme"
    assert parsed.document_type == "lab_result"


def test_document_processing_failed_defaults():
    event = DocumentProcessingFailed(event_id=uuid4(), **_base_kwargs(), job_type="pdf_conversion")
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


def test_document_conversion_requested_round_trip():
    event = DocumentConversionRequested(
        event_id=uuid4(),
        **_base_kwargs(),
        storage_key="tenants/t/patients/p/documents/d/versions/v/original.pdf",
        mime_type="application/pdf",
    )
    parsed = DocumentConversionRequested.model_validate_json(event.model_dump_json())
    assert parsed == event
    assert parsed.storage_key.endswith("original.pdf")
    assert parsed.mime_type == "application/pdf"


def test_document_analysis_requested_round_trip():
    event = DocumentAnalysisRequested(
        event_id=uuid4(),
        **_base_kwargs(),
        output_storage_key="tenants/t/patients/p/documents/d/versions/v/marker.md",
        mime_type="text/markdown",
    )
    parsed = DocumentAnalysisRequested.model_validate_json(event.model_dump_json())
    assert parsed == event
    assert parsed.output_storage_key.endswith("marker.md")
    assert parsed.mime_type == "text/markdown"


def test_organization_document_submitted_round_trip():
    event = OrganizationDocumentSubmitted(
        event_id=uuid4(),
        organization_id=uuid4(),
        document_id=uuid4(),
        patient_id=uuid4(),
        external_id="ext-42",
        document_type="lab_result",
    )
    parsed = OrganizationDocumentSubmitted.model_validate_json(event.model_dump_json())
    assert parsed == event
    assert parsed.event_version == 1
    assert parsed.external_id == "ext-42"
    assert parsed.document_type == "lab_result"


def test_organization_document_submitted_optional_fields_default():
    event = OrganizationDocumentSubmitted(
        event_id=uuid4(),
        organization_id=uuid4(),
        document_id=uuid4(),
        patient_id=uuid4(),
    )
    assert event.external_id is None
    assert event.document_type is None
    assert event.event_version == 1


def test_organization_batch_created_round_trip():
    event = OrganizationBatchCreated(
        event_id=uuid4(),
        organization_id=uuid4(),
        batch_id=uuid4(),
        total_count=3,
    )
    parsed = OrganizationBatchCreated.model_validate_json(event.model_dump_json())
    assert parsed == event
    assert parsed.event_version == 1
    assert parsed.total_count == 3


def test_organization_batch_completed_round_trip():
    event = OrganizationBatchCompleted(
        event_id=uuid4(),
        organization_id=uuid4(),
        batch_id=uuid4(),
        status="partial",
        total_count=3,
        accepted_count=2,
        failed_count=1,
    )
    parsed = OrganizationBatchCompleted.model_validate_json(event.model_dump_json())
    assert parsed == event
    assert parsed.status == "partial"
    assert parsed.accepted_count == 2
    assert parsed.failed_count == 1


def test_notification_requested_round_trip():
    event = NotificationRequested(
        event_id=uuid4(),
        notification_id=uuid4(),
        account_id=uuid4(),
        organization_id=uuid4(),
        type="document_processed",
        channel="email",
        to="patient@example.com",
        subject="Document processed — Acme Labs",
        body="Acme Labs processed your document. Sign in to view it.",
        resource_id=uuid4(),
    )
    parsed = NotificationRequested.model_validate_json(event.model_dump_json())
    assert parsed == event
    assert parsed.event_version == 1
    assert parsed.resource_type == "document"
    assert parsed.organization_id is not None


def test_notification_requested_optional_fields_default():
    event = NotificationRequested(
        event_id=uuid4(),
        notification_id=uuid4(),
        account_id=uuid4(),
        type="document_processed",
        channel="email",
        to="patient@example.com",
        subject="s",
        body="b",
        resource_id=uuid4(),
    )
    assert event.organization_id is None
    assert event.resource_type == "document"
    assert event.event_version == 1


def test_notification_delivered_round_trip():
    event = NotificationDelivered(
        event_id=uuid4(),
        notification_id=uuid4(),
        status="sent",
    )
    parsed = NotificationDelivered.model_validate_json(event.model_dump_json())
    assert parsed == event
    assert parsed.status == "sent"
    assert parsed.error_message is None
    assert parsed.event_version == 1


def test_notification_delivered_failure_carries_error():
    event = NotificationDelivered(
        event_id=uuid4(),
        notification_id=uuid4(),
        status="failed",
        error_message="smtp connect refused",
    )
    parsed = NotificationDelivered.model_validate_json(event.model_dump_json())
    assert parsed == event
    assert parsed.status == "failed"
    assert parsed.error_message == "smtp connect refused"
