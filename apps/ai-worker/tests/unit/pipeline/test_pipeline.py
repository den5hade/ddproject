from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.config.settings import Settings
from app.llm import ExtractionResult
from app.pipeline import DocumentPipeline
from contracts.events import DocumentConverted, DocumentUploaded


def _event(cls):
    uid = uuid4()
    return cls(
        event_id=uid,
        document_id=uid,
        document_version_id=uid,
        patient_id=uid,
        storage_key=("tenants/t/patients/p/documents/d/versions/v/original.pdf"),
    )


def _pipeline(mock_s3, mock_publisher):
    settings = Settings(
        s3_tenant_id="test-tenant",
        ai_api_key="test-key",
        prompts_dir="app/prompts",
    )
    pipeline = DocumentPipeline(mock_s3, mock_publisher, settings)
    pipeline._ai_client.extract_text_from_image = AsyncMock(return_value="# Page text")
    pipeline._ai_client.extract_canonical = AsyncMock(
        return_value=ExtractionResult(
            content='{"type": "generic", "subtype": "generic", '
            '"language": "ru", "document_date": null, '
            '"fields": {"note": "some text"}}',
            usage={"input": 10, "output": 5, "total": 15},
        )
    )
    return pipeline


@pytest.fixture
def mock_s3():
    s3 = MagicMock()
    s3.download_bytes.return_value = b"valid pdf bytes"
    return s3


@pytest.fixture
def mock_publisher():
    return AsyncMock()


@pytest.fixture
def pipeline(mock_s3, mock_publisher):
    return _pipeline(mock_s3, mock_publisher)


@pytest.mark.asyncio
async def test_converting_publishes_document_converted(pipeline, mock_s3, mock_publisher):
    event = _event(DocumentUploaded)

    with patch("app.ingestion.loader.convert_pdf_to_images", return_value=[b"page1"]):
        await pipeline.handle_converting(event)

    mock_s3.upload_bytes.assert_called()
    key = mock_s3.upload_bytes.call_args.args[1]
    assert key.endswith("/marker.md")

    published_keys = [c.args[0] for c in mock_publisher.publish.call_args_list]
    assert "document.converted" in published_keys


@pytest.mark.asyncio
async def test_image_upload_passes_blob_directly(mock_s3, mock_publisher):
    event = DocumentUploaded(
        event_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        patient_id=uuid4(),
        storage_key=".../original.png",
    )
    pipeline = _pipeline(mock_s3, mock_publisher)
    png_bytes = b"\x89PNG\r\n\x1a\nfake-png-data"

    async def _fake_convert(*args):
        raise AssertionError("pdf conversion should not run for images")

    with patch("app.ingestion.loader.convert_pdf_to_images", side_effect=_fake_convert):
        mock_s3.download_bytes.return_value = png_bytes
        await pipeline.handle_converting(event)

    # AI client received the original image bytes
    received_image = pipeline._ai_client.extract_text_from_image.call_args.kwargs["image_bytes"]
    assert received_image == png_bytes


@pytest.mark.asyncio
async def test_structuring_publishes_document_analysis_completed(
    pipeline, mock_s3, mock_publisher
):
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = b"# Some unstructured text"

    converted = DocumentConverted(
        event_id=uuid4(),
        document_id=event.document_id,
        document_version_id=event.document_version_id,
        patient_id=event.patient_id,
        output_storage_key=".../marker.md",
    )

    await pipeline.handle_structuring(converted)

    uploaded_keys = [c.args[1] for c in mock_s3.upload_bytes.call_args_list]
    assert any(k.endswith("/structured.md") for k in uploaded_keys)
    assert any(k.endswith("/canonical.json") for k in uploaded_keys)
    assert any(k.endswith("/classification_result.json") for k in uploaded_keys)

    published_keys = [c.args[0] for c in mock_publisher.publish.call_args_list]
    assert "document.analysis.completed" in published_keys

    event_payloads = [
        c.args[1]
        for c in mock_publisher.publish.call_args_list
        if c.args[0] == "document.analysis.completed"
    ]
    completed = event_payloads[0]
    assert completed.schema_name == "generic"
    assert completed.schema_version == "1.0.0"
    assert completed.data["canonical_key"].endswith("/canonical.json")
    assert completed.data["structured_key"].endswith("/structured.md")
    assert completed.data["classification_key"].endswith("/classification_result.json")
    assert completed.data["classification"]["document_type"] == "other"
    assert completed.data["classification"]["decision"] == "fallback"
    assert completed.data["classification"]["classifier_version"] == "2.0.0"


@pytest.mark.asyncio
async def test_structuring_uploads_valid_canonical_json(pipeline, mock_s3, mock_publisher):
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = b"# Some unstructured text"
    converted = DocumentConverted(
        event_id=uuid4(),
        document_id=event.document_id,
        document_version_id=event.document_version_id,
        patient_id=event.patient_id,
        output_storage_key=".../marker.md",
    )

    await pipeline.handle_structuring(converted)

    json_blob = next(
        c.args[0]
        for c in mock_s3.upload_bytes.call_args_list
        if c.args[1].endswith("/canonical.json")
    )
    assert b'"type": "generic"' in json_blob

    md_blob = next(
        c.args[0]
        for c in mock_s3.upload_bytes.call_args_list
        if c.args[1].endswith("/structured.md")
    )
    assert md_blob.startswith(b"---")
    assert b"type:" in md_blob


@pytest.mark.asyncio
async def test_converting_failure_publishes_failure(mock_s3, mock_publisher):
    event = _event(DocumentUploaded)
    pipeline = _pipeline(mock_s3, mock_publisher)

    with patch(
        "app.ingestion.loader.convert_pdf_to_images",
        side_effect=RuntimeError("boom"),
    ):
        await pipeline.handle_converting(event)

    published_keys = [c.args[0] for c in mock_publisher.publish.call_args_list]
    assert "document.processing.failed" in published_keys
    assert "document.converted" not in published_keys


@pytest.mark.asyncio
async def test_structuring_frontmatter_includes_source_metadata(mock_s3, mock_publisher):
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = b"# Some unstructured text"
    pipeline = _pipeline(mock_s3, mock_publisher)
    pipeline._ai_client.extract_canonical = AsyncMock(
        return_value=ExtractionResult(
            content=(
                '{"type": "laboratory", "subtype": "laboratory", "language": "ru", '
                '"document_date": null, "fields": {"results": []}}'
            ),
            usage={"input": 3, "output": 2, "total": 5},
        )
    )
    converted = DocumentConverted(
        event_id=uuid4(),
        document_id=event.document_id,
        document_version_id=event.document_version_id,
        patient_id=event.patient_id,
        output_storage_key=".../marker.md",
        original_filename="cbc.pdf",
        mime_type="application/pdf",
        sha256="abc123",
        document_type="lab_result",
    )

    await pipeline.handle_structuring(converted)

    md_blob = next(
        c.args[0]
        for c in mock_s3.upload_bytes.call_args_list
        if c.args[1].endswith("/structured.md")
    )
    assert b"cbc.pdf" in md_blob
    assert b"abc123" in md_blob

    published = next(
        c.args[1]
        for c in mock_publisher.publish.call_args_list
        if c.args[0] == "document.analysis.completed"
    )
    assert published.schema_name == "laboratory"


@pytest.mark.asyncio
async def test_structuring_maps_unknown_document_type_to_generic(mock_s3, mock_publisher):
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = b"# Some unstructured text"
    pipeline = _pipeline(mock_s3, mock_publisher)
    converted = DocumentConverted(
        event_id=uuid4(),
        document_id=event.document_id,
        document_version_id=event.document_version_id,
        patient_id=event.patient_id,
        output_storage_key=".../marker.md",
        document_type="doctor_report",
    )

    await pipeline.handle_structuring(converted)

    published = next(
        c.args[1]
        for c in mock_publisher.publish.call_args_list
        if c.args[0] == "document.analysis.completed"
    )
    assert published.schema_name == "generic"


APPOINTMENT_MARKER = """## Page 1

Электронная регистратура Югры

# Запись успешно выполнена

| | |
| :--- | :--- |
| Номер талона: | 2026030709303211960141 |
| ФИО: | Шадеркин Денис Сергеевич |
| Специальность врача: | врач-терапевт участковый |
| ФИО врача: | Моздор Милена Игоревна |
| Кабинет: | 1 МЕЛИК-КАРАМОВА 4 |
| Дата и время: | 19 марта на 09:36 |
"""


@pytest.mark.asyncio
async def test_structuring_appointment_uses_generic_extraction_but_records_type(
    mock_s3, mock_publisher
):
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = APPOINTMENT_MARKER.encode()
    pipeline = _pipeline(mock_s3, mock_publisher)
    pipeline._ai_client.extract_canonical = AsyncMock(
        return_value=ExtractionResult(
            content=(
                '{"type": "generic", "subtype": "generic", "language": "ru", '
                '"document_date": null, "fields": {"note": "appointment note"}}'
            ),
            usage={"input": 3, "output": 2, "total": 5},
        )
    )
    converted = DocumentConverted(
        event_id=uuid4(),
        document_id=event.document_id,
        document_version_id=event.document_version_id,
        patient_id=event.patient_id,
        output_storage_key=".../marker.md",
    )

    await pipeline.handle_structuring(converted)

    published = next(
        c.args[1]
        for c in mock_publisher.publish.call_args_list
        if c.args[0] == "document.analysis.completed"
    )
    assert published.schema_name == "generic"
    assert published.data["classification"]["document_type"] == "appointment"
    assert published.data["classification"]["decision"] == "accept"

    md_blob = next(
        c.args[0]
        for c in mock_s3.upload_bytes.call_args_list
        if c.args[1].endswith("/structured.md")
    )
    assert b"classification:" in md_blob
    assert b"appointment" in md_blob

    json_blob = next(
        c.args[0]
        for c in mock_s3.upload_bytes.call_args_list
        if c.args[1].endswith("/classification_result.json")
    )
    assert b'"document_type": "appointment"' in json_blob
    assert b'"prompt_key": "default"' in json_blob


AMBIGUOUS_MARKER = """| | |
| :--- | :--- |
| Кабинет: | 1 МЕЛИК-КАРАМОВА 4 |
| ФИО врача: | Моздор Милена Игоревна |

Рецепт: принимать по 1 таблетке.
"""


@pytest.mark.asyncio
async def test_structuring_ambiguous_document_uses_generic_extraction(mock_s3, mock_publisher):
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = AMBIGUOUS_MARKER.encode()
    pipeline = _pipeline(mock_s3, mock_publisher)
    converted = DocumentConverted(
        event_id=uuid4(),
        document_id=event.document_id,
        document_version_id=event.document_version_id,
        patient_id=event.patient_id,
        output_storage_key=".../marker.md",
    )

    await pipeline.handle_structuring(converted)

    published = next(
        c.args[1]
        for c in mock_publisher.publish.call_args_list
        if c.args[0] == "document.analysis.completed"
    )
    assert published.schema_name == "generic"
    assert published.data["classification"]["decision"] == "ambiguous"

    json_blob = next(
        c.args[0]
        for c in mock_s3.upload_bytes.call_args_list
        if c.args[1].endswith("/classification_result.json")
    )
    assert b'"decision": "ambiguous"' in json_blob