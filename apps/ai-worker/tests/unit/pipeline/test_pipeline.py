import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.config.settings import Settings
from app.llm import ExtractionResult
from app.pii import (
    DETECTOR_VERSION,
    HALTING_DECISIONS,
    PII_META_OPTIONAL_KEYS,
    PII_META_REQUIRED_KEYS,
    PII_POLICY_VERSION,
    InvalidPIIInputError,
    PIIDecision,
    PIIDestination,
    PIIRiskLevel,
    PIIScanResult,
    PIIScanStage,
    build_pii_meta_block,
)
from app.pipeline import DocumentPipeline
from app.pipeline.pipeline import (
    PII_DECISION_ERROR_CODES,
    PII_GATE_JOB_TYPE,
)
from contracts.events import DocumentConverted, DocumentUploaded

FINGERPRINT_SECRET = "unit-test-fingerprint-secret-0123456789"


def _event(cls):
    uid = uuid4()
    return cls(
        event_id=uid,
        document_id=uid,
        document_version_id=uid,
        patient_id=uid,
        storage_key=("tenants/t/patients/p/documents/d/versions/v/original.pdf"),
    )


def _settings(**overrides) -> Settings:
    return Settings(
        s3_tenant_id="test-tenant",
        ai_api_key="test-key",
        prompts_dir="app/prompts",
        **{"pii_fingerprint_secret": FINGERPRINT_SECRET, **overrides},
    )


def _pipeline(mock_s3, mock_publisher):
    settings = _settings()
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


def _converted(event, **overrides) -> DocumentConverted:
    return DocumentConverted(
        event_id=uuid4(),
        document_id=event.document_id,
        document_version_id=event.document_version_id,
        patient_id=event.patient_id,
        output_storage_key=".../marker.md",
        **overrides,
    )


def _uploaded_keys(mock_s3) -> list[str]:
    return [c.args[1] for c in mock_s3.upload_bytes.call_args_list]


def _uploaded_body(mock_s3, suffix: str) -> bytes:
    return next(
        c.args[0] for c in mock_s3.upload_bytes.call_args_list if c.args[1].endswith(suffix)
    )


def _published(mock_publisher, routing_key: str):
    return next(
        c.args[1] for c in mock_publisher.publish.call_args_list if c.args[0] == routing_key
    )


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
async def test_structuring_publishes_document_analysis_completed(pipeline, mock_s3, mock_publisher):
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
    assert completed.data["classification"]["classifier_version"] == "2.1.0"


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


# --- M5 Phase 11: contour 1 wiring -------------------------------------------
#
# The gate is not injected in these tests on purpose: the thing under test is
# the *wiring*, and a stubbed gate would only assert that the stub was called.
# Every test below runs the real DefaultPIIGate over real Russian text, so a
# detector that stops matching, or a policy that starts halting clean documents,
# fails here rather than in production.


SECRET_MARKER = """## Page 1

# Справка

| | |
| :--- | :--- |
| ФИО: | Шадеркин Денис Сергеевич |
| СНИЛС: | 123-456-789 00 |
| api_key: | sk-live-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 |
"""
"""A document carrying identifiers *and* a credential.

The credential line is inert today: ``SecretPIIDetector`` is Phase 13, so the
``api_key`` row is currently invisible to the chain and the document is allowed
through on the ``СНИЛС`` alone.

That is deliberate, and it makes this fixture a **tripwire for Phase 13**. The
day the secret detector lands, this document's decision becomes ``BLOCK``, the
pipeline halts, and the allow-path tests below start failing with a zero-upload
``document.processing.failed``. That failure is the signal that the block source
works end-to-end — it should be resolved by splitting the fixture in two (an
identifier-only document for the allow path, a credential document for the block
path), not by loosening the assertions.
"""


def test_pipeline_refuses_to_start_without_fingerprint_secret(mock_s3, mock_publisher):
    """Fail closed at start-up, not on the first document."""
    settings = _settings(pii_fingerprint_secret="")

    with pytest.raises(InvalidPIIInputError):
        DocumentPipeline(mock_s3, mock_publisher, settings)


def test_every_halting_decision_has_an_error_code():
    """A new halting decision must not reach production as a KeyError."""
    assert set(PII_DECISION_ERROR_CODES) == set(HALTING_DECISIONS)
    assert PII_DECISION_ERROR_CODES[PIIDecision.REVIEW] == "PII_REVIEW_REQUIRED"
    assert PII_DECISION_ERROR_CODES[PIIDecision.BLOCK] == "PII_BLOCKED"


@pytest.mark.asyncio
async def test_structuring_uploads_pii_result_before_publish(pipeline, mock_s3, mock_publisher):
    """The artifact is on disk before the event that references it exists.

    ``MagicMock.call_args_list`` is ordered globally per mock, so the two
    upload indices are comparable: the PII upload must not be the last thing
    that happens, and the publish must come after every upload.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = b"# Some unstructured text"

    await pipeline.handle_structuring(_converted(event))

    uploads = mock_s3.upload_bytes.call_args_list
    pii_index = next(i for i, c in enumerate(uploads) if c.args[1].endswith("/pii_result.json"))
    canonical_index = next(
        i for i, c in enumerate(uploads) if c.args[1].endswith("/canonical.json")
    )
    assert pii_index < canonical_index

    published = _published(mock_publisher, "document.analysis.completed")
    assert published.data["pii_key"].endswith("/pii_result.json")


@pytest.mark.asyncio
async def test_structuring_pii_artifact_is_schema_conformant(pipeline, mock_s3, mock_publisher):
    """The uploaded blob validates as PIIScanResult and matches the event block."""
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = b"# Some unstructured text"

    await pipeline.handle_structuring(_converted(event))

    blob = json.loads(_uploaded_body(mock_s3, "/pii_result.json"))
    parsed = PIIScanResult.model_validate(blob)
    assert parsed.stage == "document"
    assert parsed.destination == "internal_llm"
    assert parsed.findings_count == len(parsed.findings)

    completed = _published(mock_publisher, "document.analysis.completed")
    assert completed.data["pii"] == build_pii_meta_block(result=parsed)
    assert completed.data["pii_key"].endswith("/pii_result.json")


@pytest.mark.asyncio
async def test_structuring_pii_block_present_in_frontmatter_and_event(
    pipeline, mock_s3, mock_publisher
):
    """One build, two surfaces: they cannot disagree about the verdict."""
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = b"# Some unstructured text"

    await pipeline.handle_structuring(_converted(event))

    md_blob = _uploaded_body(mock_s3, "/structured.md")
    assert b"pii:" in md_blob

    completed = _published(mock_publisher, "document.analysis.completed")
    block = completed.data["pii"]
    assert set(PII_META_REQUIRED_KEYS) <= set(block)
    assert set(block) == set(PII_META_REQUIRED_KEYS) | set(PII_META_OPTIONAL_KEYS)
    assert block["decision"] == "allow"


@pytest.mark.asyncio
async def test_structuring_detects_pii_and_still_continues(pipeline, mock_s3, mock_publisher):
    """PII presence alone never halts; it is recorded and the document proceeds."""
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = SECRET_MARKER.encode()

    await pipeline.handle_structuring(_converted(event))

    completed = _published(mock_publisher, "document.analysis.completed")
    assert completed.data["pii"]["decision"] in {"allow", "allow_with_warning"}
    assert completed.data["pii"]["findings_count"] > 0
    assert pipeline._ai_client.extract_canonical.called
    assert any(k.endswith("/canonical.json") for k in _uploaded_keys(mock_s3))


@pytest.mark.asyncio
async def test_structuring_does_not_leak_raw_pii_into_artifacts(pipeline, mock_s3, mock_publisher):
    """The artifacts carry the masked finding, never the value behind it."""
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = SECRET_MARKER.encode()

    await pipeline.handle_structuring(_converted(event))

    assert _uploaded_keys(mock_s3), "expected the clean path to upload artifacts"

    blob = json.loads(_uploaded_body(mock_s3, "/pii_result.json"))
    assert blob["findings_count"] > 0
    for finding in blob["findings"]:
        assert "value" not in finding
        assert "value_fingerprint" not in finding

    # structured.md embeds the pii block; the block is a summary, so it carries
    # no per-finding masked_value at all -- only the counts. What must never
    # appear anywhere is the raw identifier the detector saw.
    frontmatter = _uploaded_body(mock_s3, "/structured.md").decode("utf-8")
    assert "value_fingerprint" not in frontmatter
    assert "Шадеркин Денис Сергеевич" not in frontmatter
    assert "123-456-789 00" not in frontmatter


@pytest.mark.asyncio
async def test_structuring_halting_decision_writes_nothing(mock_s3, mock_publisher):
    """REVIEW/BLOCK: no artifact, no completed event, only the failure event."""
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = SECRET_MARKER.encode()
    pipeline = _pipeline(mock_s3, mock_publisher)
    pipeline._pii_gate = _StubGate(PIIDecision.REVIEW)

    await pipeline.handle_structuring(_converted(event))

    assert mock_s3.upload_bytes.call_args_list == []
    assert pipeline._ai_client.extract_canonical.called is False

    published_keys = [c.args[0] for c in mock_publisher.publish.call_args_list]
    assert published_keys == ["document.processing.failed"]

    failure = _published(mock_publisher, "document.processing.failed")
    assert failure.job_type == PII_GATE_JOB_TYPE
    assert failure.error_code == PII_DECISION_ERROR_CODES[PIIDecision.REVIEW]


@pytest.mark.asyncio
async def test_structuring_block_and_review_carry_different_codes(mock_s3, mock_publisher):
    """They are different events for whoever clears the queue."""
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = b"# clean"
    pipeline = _pipeline(mock_s3, mock_publisher)

    pipeline._pii_gate = _StubGate(PIIDecision.REVIEW)
    await pipeline.handle_structuring(_converted(event))
    review = _published(mock_publisher, "document.processing.failed")

    mock_s3.upload_bytes.reset_mock()
    mock_publisher.publish.reset_mock()
    pipeline._pii_gate = _StubGate(PIIDecision.BLOCK)
    await pipeline.handle_structuring(_converted(event))
    block = _published(mock_publisher, "document.processing.failed")

    assert review.error_code == "PII_REVIEW_REQUIRED"
    assert block.error_code == "PII_BLOCKED"


@pytest.mark.asyncio
async def test_structuring_gate_runs_before_extraction(pipeline):
    """Ordering: a halting verdict must not cost an LLM call."""
    pipeline._pii_gate = _StubGate(PIIDecision.BLOCK)

    await pipeline.handle_structuring(_converted(_event(DocumentUploaded)))

    assert pipeline._ai_client.extract_canonical.called is False


class _StubGate:
    """A gate that returns a fixed verdict, for the halt paths only.

    The allow path is exercised by the real gate in the tests above; this exists
    because there is no *implemented* detector that yields BLOCK — the secret
    detector is Phase 13 — so BLOCK is otherwise unreachable in a test at all.
    """

    def __init__(self, decision: PIIDecision) -> None:
        self._decision = decision

    async def inspect(self, document, context) -> PIIScanResult:
        return PIIScanResult(
            decision=self._decision,
            risk_level=PIIRiskLevel.HIGH,
            stage=PIIScanStage.DOCUMENT,
            destination=PIIDestination.INTERNAL_LLM,
            findings=[],
            findings_count=0,
            detector_version=DETECTOR_VERSION,
            policy_version=PII_POLICY_VERSION,
            processed_at=datetime.now(UTC),
            category_counts={},
            reasons=[f"stubbed {self._decision.value}"],
            warnings=[],
        )
