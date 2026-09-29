import json
from datetime import UTC, datetime
from pathlib import Path
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
    DocumentPIIGateResult,
    InvalidPIIInputError,
    PIIDecision,
    PIIDestination,
    PIIRiskLevel,
    PIIScanResult,
    PIIScanStage,
    build_pii_meta_block,
)
from app.pii.exceptions import PIIRedactionError
from app.pipeline import DocumentPipeline
from app.pipeline.pipeline import (
    PII_CANONICAL_GATE_JOB_TYPE,
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


IDENTIFIER_MARKER = """## Page 1

# Справка

| | |
| :--- | :--- |
| ФИО: | Шадеркин Денис Сергеевич |
| СНИЛС: | 123-456-789 00 |
"""
"""A document carrying identifiers and no credential — the allow path.

Split from :data:`CREDENTIAL_MARKER` in M5 Phase 13. The two used to be one
fixture, and that fixture was a **tripwire**: ``SecretPIIDetector`` did not exist,
so the ``api_key`` row was invisible to the chain, the document was allowed
through on the ``СНИЛС`` alone, and the day the secret detector landed every
allow-path assertion here began failing with a zero-upload
``document.processing.failed``.

A failing test is the correct way to learn that a block source works, but the
repair is to split the fixture, not to weaken the assertions — one document per
verdict, so that a later change to either verdict is attributable to whichever
one the fixture actually exercises.
"""

CREDENTIAL_MARKER = """## Page 1

# Справка

| | |
| :--- | :--- |
| ФИО: | Шадеркин Денис Сергеевич |
| api_key: | sk-live-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 |
"""
"""A document carrying a live-shaped credential — the block path.

This is the fixture the tripwire was asking for. ``SecretPIIDetector`` is the
only source of ``BLOCK`` (``PII_DECISION_ERROR_CODES`` and
:data:`~app.pii.policy.HALTING_DECISIONS` say so), so before Phase 13 no test
could drive the real gate to a halt at all: every halting test substituted
:class:`_StubGate` and proved the pipeline honours a verdict it was handed,
never that the pipeline can reach one. Both halves of that are asserted in
``test_a_credential_in_a_real_document_blocks_through_the_real_gate``.
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
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()

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
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()

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
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()
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


@pytest.mark.asyncio
async def test_a_credential_in_a_real_document_blocks_through_the_real_gate(
    pipeline, mock_s3, mock_publisher
):
    """The block path end-to-end: no stub, no injected verdict.

    Every other halting test in this module replaces the gate with
    :class:`_StubGate`, so they prove the pipeline honours a verdict it was
    handed. None of them proves the pipeline can *reach* one — and before M5
    Phase 13 it could not, because ``SecretPIIDetector`` is the only source of
    ``BLOCK`` and did not exist. This is that test: a credential in a document,
    the real chain, the real policy, and the four assertions that together mean
    the document is stopped *before* it is used —

    - nothing is uploaded, not even the PII artifact that records the finding;
    - the LLM is never called, so no credential reaches a prompt;
    - only ``document.processing.failed`` is published, with ``PII_BLOCKED``;
    - the raw credential appears in no published payload.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = CREDENTIAL_MARKER.encode()

    await pipeline.handle_structuring(_converted(event))

    assert mock_s3.upload_bytes.call_args_list == []
    assert pipeline._ai_client.extract_canonical.called is False

    published_keys = [c.args[0] for c in mock_publisher.publish.call_args_list]
    assert published_keys == ["document.processing.failed"]
    failure = _published(mock_publisher, "document.processing.failed")
    assert failure.job_type == PII_GATE_JOB_TYPE
    assert failure.error_code == PII_DECISION_ERROR_CODES[PIIDecision.BLOCK]

    serialised = json.dumps([c.args[1] for c in mock_publisher.publish.call_args_list], default=str)
    assert "sk-live-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" not in serialised


@pytest.mark.asyncio
async def test_identifiers_alone_do_not_block_even_with_a_real_gate(
    pipeline, mock_s3, mock_publisher
):
    """The other half of the pair, and the one that keeps the first honest.

    A gate that halted on every document would pass
    ``test_a_credential_in_a_real_document_blocks_through_the_real_gate`` and be
    useless. ``IDENTIFIER_MARKER`` differs from :data:`CREDENTIAL_MARKER` only in
    the credential row, so the allow decision here is attributable to the secret
    detector and not to the fixture being different in some other way.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()

    await pipeline.handle_structuring(_converted(event))

    completed = _published(mock_publisher, "document.analysis.completed")
    assert completed.data["pii"]["decision"] in {"allow", "allow_with_warning"}
    assert completed.data["pii"]["findings_count"] > 0


# --- contour 2: the canonical-output guard (M5 Phase 14) ----------------------
#
# Contour 1's tests above all feed the *marker* to the gate, which is correct and
# insufficient: the observed leak never appeared in `marker.md` as a field the
# gate declined to read. It appeared in `canonical.json` because the extraction
# model copied a declined patient's name into free prose, and it then reached
# `document_extractions.data` because `DocumentAnalysisCompleted.data` is dumped
# verbatim. Everything below therefore keeps the marker clean and puts the PII in
# the *extraction result*, which is where the leak actually was.

CANONICAL_FIXTURES = Path("tests/fixtures/pii/canonical")
LEAKED_PATIENT = "Кузнецова Александра Петровича"
LEAKED_TICKET = "2026030710155500000001"


def _leak_notes() -> dict[str, str]:
    """The two observed payload shapes, rebuilt with invented values (§7 decision 9)."""
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))["fields"]["note"]
        for path in sorted(CANONICAL_FIXTURES.rglob("*.json"))
    }


def _pipeline_with_extraction(
    mock_s3, mock_publisher, note: str, document_date: str = "2026-03-05"
):
    """A pipeline whose extraction returns ``note`` — the leak's actual position.

    The marker stays clean, so contour 1 allows the document through and the test
    measures contour 2 rather than re-testing contour 1. The date is set because
    the payload shape has one, and Phase 14 had to decide what happens to it.
    """
    pipeline = _pipeline(mock_s3, mock_publisher)
    pipeline._ai_client.extract_canonical = AsyncMock(
        return_value=ExtractionResult(
            content=json.dumps(
                {
                    "type": "generic",
                    "subtype": "generic",
                    "language": "ru",
                    "document_date": document_date,
                    "fields": {"note": note},
                },
                ensure_ascii=False,
            ),
            usage={"input": 10, "output": 5, "total": 15},
        )
    )
    return pipeline


@pytest.mark.parametrize("note", sorted(_leak_notes().values()), ids=sorted(_leak_notes()))
@pytest.mark.asyncio
async def test_canonical_guard_sanitizes_all_three_sinks(mock_s3, mock_publisher, note):
    """The leak is masked in ``canonical.json``, ``structured.md`` *and* the event.

    One loop over three surfaces rather than three tests, because the failure this
    phase exists to prevent is precisely the kind that a per-surface test would
    not catch: the guard could be wired after ``canonical.model_dump`` and every
    one of the three would then have to be asserted separately, and a fourth sink
    added later would have been forgotten. As written, the sink list is the
    assertion — a new surface has to be added here to be covered at all.

    The marker is clean, so the only thing that can have masked this note is the
    canonical guard.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = b"# clean marker"
    pipeline = _pipeline_with_extraction(mock_s3, mock_publisher, note)

    await pipeline.handle_structuring(_converted(event))

    canonical_blob = json.loads(_uploaded_body(mock_s3, "/canonical.json"))
    markdown = _uploaded_body(mock_s3, "/structured.md").decode("utf-8")
    completed = _published(mock_publisher, "document.analysis.completed")

    surfaces = {
        "canonical.json": canonical_blob["fields"]["note"],
        "structured.md": markdown,
        "event data": completed.data["fields"]["note"],
    }
    for name, surface in surfaces.items():
        assert LEAKED_PATIENT not in surface, f"patient name reached {name}"
        assert LEAKED_TICKET not in surface, f"ticket number reached {name}"
        assert "[PERSON_NAME]" in surface, f"{name} lost the note entirely"


@pytest.mark.asyncio
async def test_canonical_guard_keeps_the_clinician_and_the_service_date(mock_s3, mock_publisher):
    """A masked-everything document would pass the test above. This one would not.

    The narrowness claim needs its own test, and it needs a surface that renders
    the value *outside* the note: ``render_document`` writes
    ``canonical.document_date`` into the frontmatter, so a guard that redacted the
    service date would publish ``document_date: '[DATE_OF_BIRTH]'`` and leave the
    note looking perfectly sanitized. A clinician's name is the other half — it is
    in the payload on purpose (IMPL_ARCH §3.1) and is ``ALLOW`` at every
    destination, so masking it is a fidelity loss with no privacy benefit.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = b"# clean marker"
    note = _leak_notes()["synthetic-analysis-note-01.json"]
    pipeline = _pipeline_with_extraction(mock_s3, mock_publisher, note)

    await pipeline.handle_structuring(_converted(event))

    canonical_blob = json.loads(_uploaded_body(mock_s3, "/canonical.json"))
    markdown = _uploaded_body(mock_s3, "/structured.md").decode("utf-8")

    assert canonical_blob["document_date"] == "2026-03-05"
    # YAML quotes the date, so the assertion is on the value the frontmatter
    # carries rather than on an unquoted rendering that would never appear.
    assert "document_date: '2026-03-05'" in markdown
    assert "[DATE_OF_BIRTH]" not in markdown

    assert "Петров И. С." in canonical_blob["fields"]["note"]
    assert "(М, 39 лет)" in canonical_blob["fields"]["note"]
    assert "гипертоническая болезнь I стадии" in canonical_blob["fields"]["note"]


@pytest.mark.asyncio
async def test_the_extracted_payload_the_pipeline_holds_is_the_sanitized_one(
    mock_s3, mock_publisher
):
    """One object, rebound before any consumer reads it.

    The three-sink test above proves the *outputs* are clean. This proves the
    reason they can be, which is a claim about ordering: the guard's return value
    is assigned back over the extracted model, so ``render_document`` and the event
    cannot be reading a pre-guard object. A test that only checked the outputs
    would still pass if the rebinding were dropped *and* a later sanitize-a-copy
    step were added, and the object in the middle would be the leaking one.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = b"# clean marker"
    pipeline = _pipeline_with_extraction(
        mock_s3, mock_publisher, _leak_notes()["synthetic-registration-note-01.json"]
    )
    rebuilt: list[object] = []
    original = pipeline._build_frontmatter

    def record(*args, **kwargs):
        rebuilt.append(args[1] if len(args) > 1 else None)
        return original(*args, **kwargs)

    pipeline._build_frontmatter = record

    await pipeline.handle_structuring(_converted(event))

    assert rebuilt, "expected the frontmatter to have been rendered"
    assert LEAKED_PATIENT not in json.dumps(rebuilt[0].model_dump(mode="json"), ensure_ascii=False)


@pytest.mark.asyncio
async def test_canonical_guard_blocks_a_secret_reaching_any_sink(mock_s3, mock_publisher):
    """A credential the *model* invented is still a credential, and it halts.

    Contour 1's block test proves the gate stops a credential in the marker. This
    proves contour 2 stops one the extraction step produced, which is the case a
    document gate structurally cannot see. The marker is clean, so the only
    thing that can produce this ``BLOCK`` is the canonical guard.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = b"# clean marker"
    pipeline = _pipeline_with_extraction(
        mock_s3,
        mock_publisher,
        f"Пациент: {LEAKED_PATIENT}. Ключ доступа: sk-live-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    )

    await pipeline.handle_structuring(_converted(event))

    keys = _uploaded_keys(mock_s3)
    assert not any(k.endswith("/canonical.json") for k in keys)
    assert not any(k.endswith("/structured.md") for k in keys)

    published_keys = [c.args[0] for c in mock_publisher.publish.call_args_list]
    assert published_keys == ["document.processing.failed"]

    failure = _published(mock_publisher, "document.processing.failed")
    assert failure.job_type == PII_CANONICAL_GATE_JOB_TYPE
    assert failure.error_code == PII_DECISION_ERROR_CODES[PIIDecision.BLOCK]

    serialised = json.dumps([c.args[1] for c in mock_publisher.publish.call_args_list], default=str)
    assert "sk-live-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" not in serialised


@pytest.mark.asyncio
async def test_a_canonical_halt_keeps_the_contour_1_artifact_and_its_failure_is_its_own(
    mock_s3, mock_publisher
):
    """The halt is contour-2's, and the audit trail says so.

    Two things are easy to get wrong and both are asserted here. First, the
    ``pii_result.json`` from contour 1 is *still on disk*: it is the gate's own
    audit record, it carries no patient text, and "no artifacts at all" would be
    the wrong claim. Second, the failure is filed under its own job type, so a
    document stopped after a successful source scan is not filed as a source-scan
    problem and sent to the wrong queue.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()
    pipeline = _pipeline_with_extraction(
        mock_s3,
        mock_publisher,
        "Ключ доступа: sk-live-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    )

    await pipeline.handle_structuring(_converted(event))

    keys = _uploaded_keys(mock_s3)
    assert [k for k in keys if k.endswith("/pii_result.json")]  # contour 1's audit record
    assert not any(k.endswith("/canonical.json") for k in keys)

    failure = _published(mock_publisher, "document.processing.failed")
    assert failure.job_type == PII_CANONICAL_GATE_JOB_TYPE
    assert failure.job_type != PII_GATE_JOB_TYPE
    assert failure.error_code == PII_DECISION_ERROR_CODES[PIIDecision.BLOCK]


@pytest.mark.asyncio
async def test_a_clean_extraction_is_uploaded_unchanged(mock_s3, mock_publisher):
    """A guard that rewrote every document would pass every test above.

    This is the counterpart: a payload with nothing to redact goes out byte for
    byte as the model built it, and the pipeline does not even rebuild the model —
    the "skip the rebuild when nothing is REDACT" fast path exists so that a
    document carrying only ``ALLOW``-actioned findings (a doctor, a clinic) cannot
    fail a validation it never needed to pass.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = b"# clean marker"
    note = "Осмотр проведен. Врач: Петров И. С. Диагноз: гипертоническая болезнь I стадии."
    pipeline = _pipeline_with_extraction(mock_s3, mock_publisher, note)

    await pipeline.handle_structuring(_converted(event))

    canonical_blob = json.loads(_uploaded_body(mock_s3, "/canonical.json"))
    assert canonical_blob["fields"]["note"] == note


@pytest.mark.asyncio
async def test_a_failing_rebuild_halts_rather_than_uploading_the_original(mock_s3, mock_publisher):
    """A sanitizer that raises is a halt, never a pass-through.

    The tempting failure mode is a ``except`` that logs and continues, which would
    upload the *unsanitized* object with a reassuring log line. The guard's
    contract is that the exception reaches the pipeline's fail-closed branch, so
    the test replaces the redactor with one that always fails and asserts that
    nothing is uploaded at all.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = b"# clean marker"
    pipeline = _pipeline_with_extraction(
        mock_s3, mock_publisher, _leak_notes()["synthetic-registration-note-01.json"]
    )

    class ExplodingRedactor:
        def redact(self, markdown, findings):
            raise PIIRedactionError("no span for this value")

    pipeline._pii_guard.redactor = ExplodingRedactor()

    await pipeline.handle_structuring(_converted(event))

    keys = _uploaded_keys(mock_s3)
    assert not any(k.endswith("/canonical.json") for k in keys)
    assert not any(k.endswith("/structured.md") for k in keys)

    failure = _published(mock_publisher, "document.processing.failed")
    assert failure.job_type == PII_CANONICAL_GATE_JOB_TYPE
    assert failure.error_code == "PII_CANONICAL_GUARD_FAILED"


class _StubGate:
    """A gate that returns a fixed verdict, for the halt paths only.

    The allow path *and* the real block path are both exercised by the real gate
    in the tests above; this exists so a test can assert that the pipeline
    honours a specific verdict without also asserting that the chain produced
    it, which is what the ``REVIEW`` and ordering tests need — ``REVIEW`` is a
    verdict the real chain does not currently reach, and "a halting verdict must
    not cost an LLM call" is a claim about the pipeline's order of operations,
    not about the detector's recall.
    """

    def __init__(self, decision: PIIDecision) -> None:
        self._decision = decision

    async def evaluate_document(self, document, context) -> DocumentPIIGateResult:
        # Phase 15: the pipeline calls evaluate_document, not inspect, and needs
        # the in-process `redact` beside it. Both halting decisions have no
        # REDACT action, so the empty action map is faithful rather than lazy.
        return DocumentPIIGateResult(
            scan_result=PIIScanResult(
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
            ),
            findings=[],
            actions={},
        )

    def redact(self, markdown: str, result: DocumentPIIGateResult) -> str:
        # No action is REDACT, so the identity return is the honest one.
        return markdown


# --- 15. the untrusted-LLM boundary, end to end -------------------------------


def _external_pipeline(mock_s3, mock_publisher) -> DocumentPipeline:
    """The real pipeline with ``llm_mode=external_llm`` and a non-trusted URL.

    Nothing is stubbed: this is the configuration the phase exists for, and the
    point of these tests is that the *production* wiring redacts, uploads the
    record, and reports the artifact — not that a stub can be made to.
    """
    settings = _settings(llm_mode="external_llm", ai_base_url="https://provider.example/v1")
    pipeline = DocumentPipeline(mock_s3, mock_publisher, settings)
    pipeline._ai_client.extract_canonical = AsyncMock(
        return_value=ExtractionResult(
            content='{"type": "generic", "subtype": "generic", "language": "ru", '
            '"document_date": null, "fields": {"note": "some text"}}',
            usage={"input": 10, "output": 5, "total": 15},
        )
    )
    return pipeline


@pytest.mark.asyncio
async def test_the_trusted_provider_receives_the_marker_byte_for_byte(
    mock_s3, mock_publisher
):
    """The default must not change a single character sent to the model.

    The regression this guards is the expensive kind: "make redaction
    unconditional" would pass every external test and quietly destroy the
    fidelity of every document the platform processes.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()
    pipeline = _pipeline(mock_s3, mock_publisher)

    await pipeline.handle_structuring(_converted(event))

    sent = pipeline._ai_client.extract_canonical.call_args.kwargs["markdown"]
    assert sent == IDENTIFIER_MARKER
    assert "Шадеркин Денис Сергеевич" in sent


@pytest.mark.asyncio
async def test_the_external_provider_receives_redacted_markdown(mock_s3, mock_publisher):
    """**Phase 15's accept criterion.** The model must not see what leaves.

    Asserted on the kwarg the client was actually called with, not on an
    artifact: the artifact could be right while the call sends the original, and
    that is the leak this milestone was assembled to close.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()
    pipeline = _external_pipeline(mock_s3, mock_publisher)

    await pipeline.handle_structuring(_converted(event))

    sent = pipeline._ai_client.extract_canonical.call_args.kwargs["markdown"]
    assert "Шадеркин Денис Сергеевич" not in sent
    assert "123-456-789 00" not in sent
    assert "[PERSON_NAME]" in sent
    assert sent != IDENTIFIER_MARKER


@pytest.mark.asyncio
async def test_the_redacted_artifact_is_uploaded_and_named_in_the_event(
    mock_s3, mock_publisher
):
    """The record of what crossed the boundary, on the same run that crossed it."""
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()
    pipeline = _external_pipeline(mock_s3, mock_publisher)

    await pipeline.handle_structuring(_converted(event))

    keys = _uploaded_keys(mock_s3)
    assert any(key.endswith("/redacted.md") for key in keys)

    body = _uploaded_body(mock_s3, "redacted.md").decode()
    assert "Шадеркин Денис Сергеевич" not in body
    assert "[PERSON_NAME]" in body

    completed = _published(mock_publisher, "document.analysis.completed")
    assert completed.data["redacted_key"].endswith("/redacted.md")


@pytest.mark.asyncio
async def test_no_redacted_artifact_and_no_event_key_on_the_trusted_path(
    mock_s3, mock_publisher
):
    """A key that is null on every default run is a schema change for a non-event.

    ``DocumentAnalysisCompleted.data`` is a cross-package contract (R11), so an
    optional key that appears only when a redaction happened is the honest shape
    of the change: at the trusted destination there is nothing to point at.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()
    pipeline = _pipeline(mock_s3, mock_publisher)

    await pipeline.handle_structuring(_converted(event))

    assert not any(key.endswith("/redacted.md") for key in _uploaded_keys(mock_s3))
    completed = _published(mock_publisher, "document.analysis.completed")
    assert "redacted_key" not in completed.data


@pytest.mark.asyncio
async def test_the_redacted_artifact_is_uploaded_before_the_model_is_called(
    mock_s3, mock_publisher
):
    """Ordering, asserted by the order the mocks were called in.

    Phase 11's invariant — a verdict uploaded before the extraction call so it
    survives an LLM failure — now covers the *text* as well as the verdict. If
    the model call raises, the question "what would have been sent?" must still
    have an answer on disk.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()
    pipeline = _external_pipeline(mock_s3, mock_publisher)

    await pipeline.handle_structuring(_converted(event))

    uploads = [c.args[1] for c in mock_s3.upload_bytes.call_args_list]
    # pii_result.json, then redacted.md, and both before canonical.json.
    pii_index = next(i for i, key in enumerate(uploads) if key.endswith("pii_result.json"))
    redacted_index = next(i for i, key in enumerate(uploads) if key.endswith("redacted.md"))
    canonical_index = next(i for i, key in enumerate(uploads) if key.endswith("canonical.json"))
    assert pii_index < redacted_index < canonical_index


@pytest.mark.asyncio
async def test_a_model_failure_leaves_both_the_verdict_and_the_text_on_disk(
    mock_s3, mock_publisher
):
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()
    pipeline = _external_pipeline(mock_s3, mock_publisher)
    pipeline._ai_client.extract_canonical = AsyncMock(side_effect=RuntimeError("provider down"))

    await pipeline.handle_structuring(_converted(event))

    keys = _uploaded_keys(mock_s3)
    assert any(key.endswith("pii_result.json") for key in keys)
    assert any(key.endswith("redacted.md") for key in keys)
    assert not any(key.endswith("canonical.json") for key in keys)


@pytest.mark.asyncio
async def test_a_redaction_failure_stops_the_document_before_the_model(
    mock_s3, mock_publisher
):
    """A document whose PII could not be removed must not be sent at all.

    Without this branch the handler's blanket ``except`` would report the
    failure as ``markdown_structuring``, which reads as a provider problem and
    loses the fact that a security control stopped the document.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()
    pipeline = _external_pipeline(mock_s3, mock_publisher)
    pipeline._pii_gate.redact = MagicMock(
        side_effect=PIIRedactionError("cannot redact a snils finding from the text: neither")
    )

    await pipeline.handle_structuring(_converted(event))

    assert pipeline._ai_client.extract_canonical.called is False
    published_keys = [c.args[0] for c in mock_publisher.publish.call_args_list]
    assert published_keys == ["document.processing.failed"]

    failure = _published(mock_publisher, "document.processing.failed")
    assert failure.job_type == PII_GATE_JOB_TYPE
    assert failure.error_code == "PII_REDACTION_FAILED"


@pytest.mark.asyncio
async def test_a_redaction_failure_message_carries_no_patient_value(
    mock_s3, mock_publisher
):
    """The failure is published to a queue operators read.

    ``PIIRedactionError``'s message names the category and the offsets, never
    the value, by construction — asserted here because "by construction" is a
    claim about a message that a future edit could widen.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()
    pipeline = _external_pipeline(mock_s3, mock_publisher)
    pipeline._pii_gate.redact = MagicMock(
        side_effect=PIIRedactionError("cannot redact a snils finding from the text: neither")
    )

    await pipeline.handle_structuring(_converted(event))

    failure = _published(mock_publisher, "document.processing.failed")
    assert "Шадеркин" not in failure.error_message
    assert "123-456-789 00" not in failure.error_message


@pytest.mark.asyncio
async def test_a_redaction_failure_writes_no_redacted_artifact(
    mock_s3, mock_publisher
):
    """The artifact records what was sent, so it cannot exist for a document
    whose text was never assembled."""
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()
    pipeline = _external_pipeline(mock_s3, mock_publisher)
    pipeline._pii_gate.redact = MagicMock(
        side_effect=PIIRedactionError("cannot redact a snils finding from the text: neither")
    )

    await pipeline.handle_structuring(_converted(event))

    assert not any(key.endswith("redacted.md") for key in _uploaded_keys(mock_s3))
    # The scan's own audit record stays: it is the reason the redaction failed.
    assert any(key.endswith("pii_result.json") for key in _uploaded_keys(mock_s3))


@pytest.mark.asyncio
async def test_the_page_count_describes_the_document_not_the_redacted_text(
    mock_s3, mock_publisher
):
    """``## Page N`` markers are the input, and the input is untouched.

    Counting the redacted text would still give the right number today — the
    placeholders do not contain page markers — which is exactly why this is
    pinned: it is the kind of substitution that is harmless until a redaction
    rule starts touching a page marker, and then the frontmatter is wrong with
    no test failing.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()
    pipeline = _external_pipeline(mock_s3, mock_publisher)

    await pipeline.handle_structuring(_converted(event))

    structured = _uploaded_body(mock_s3, "structured.md").decode()
    assert "page_count: 1" in structured


@pytest.mark.asyncio
async def test_the_worker_refuses_to_start_on_an_untrusted_url_at_the_default_mode():
    """D3 at the choke point that matters: construction, not first document."""
    settings = _settings(ai_base_url="https://provider.example/v1")

    with pytest.raises(InvalidPIIInputError):
        DocumentPipeline(MagicMock(), AsyncMock(), settings)


@pytest.mark.asyncio
async def test_the_canonical_is_built_from_redacted_output_so_it_carries_placeholders(
    mock_s3, mock_publisher
):
    """D4's accepted fidelity cost, made observable.

    The model echoes what it was sent, so a canonical built from redacted input
    carries ``[PERSON_NAME]`` where the identifier was. That is **correct
    behaviour** on this path, and a reader who does not know it will file it as
    a defect. The guard is still running over it; it simply never sees the
    original, because the LLM never did either.
    """
    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()
    pipeline = _external_pipeline(mock_s3, mock_publisher)
    pipeline._ai_client.extract_canonical = AsyncMock(
        return_value=ExtractionResult(
            content=json.dumps(
                {
                    "type": "generic",
                    "subtype": "generic",
                    "language": "ru",
                    "document_date": None,
                    "fields": {"note": "Пациент [PERSON_NAME]"},
                }
            ),
            usage={"input": 10, "output": 5, "total": 15},
        )
    )

    await pipeline.handle_structuring(_converted(event))

    canonical = _uploaded_body(mock_s3, "canonical.json").decode()
    assert "[PERSON_NAME]" in canonical
    assert "Шадеркин Денис Сергеевич" not in canonical


@pytest.mark.asyncio
async def test_redaction_available_false_escalates_to_review_not_to_a_rewrite(
    mock_s3, mock_publisher
):
    """A construction-level test of the fail-closed path, on purpose.

    ``REDACTION_AVAILABLE`` stays a module constant ``True`` (Phase 12 decision
    2), so the escalation is unreachable in production and is exercised by
    injecting a gate built without a working redactor. Phase 15 must **not** add
    a settings flag to reach it — that would be the fail-open the constant was
    chosen to prevent.
    """
    from app.pii import build_document_gate
    from app.pii import gate as gate_module

    event = _event(DocumentUploaded)
    mock_s3.download_bytes.return_value = IDENTIFIER_MARKER.encode()
    pipeline = _external_pipeline(mock_s3, mock_publisher)
    # The patch has to span the *scan*, not the construction: the constant is
    # read by the policy-context builder each time it runs, which is what keeps
    # it a constant about this codebase rather than a value frozen into a gate.
    with patch.object(gate_module, "REDACTION_AVAILABLE", False):
        pipeline._pii_gate = build_document_gate(
            _settings(llm_mode="external_llm", ai_base_url="https://provider.example/v1")
        )
        await pipeline.handle_structuring(_converted(event))

    published_keys = [c.args[0] for c in mock_publisher.publish.call_args_list]
    assert published_keys == ["document.processing.failed"]
    failure = _published(mock_publisher, "document.processing.failed")
    assert failure.error_code == PII_DECISION_ERROR_CODES[PIIDecision.REVIEW]
    assert pipeline._ai_client.extract_canonical.called is False


def test_the_pipeline_docstring_still_names_the_ocr_boundary():
    """A documented gap that a refactor can silently delete is not a gap.

    Same reason as Phase 6's "a test asserts the module still claims to be
    unlocked": the claim about OCR is the only thing standing between an
    operator and the belief that ``llm_mode`` protects the image.
    """
    from app.pipeline import pipeline as pipeline_module

    doc = pipeline_module.__doc__ or ""

    assert "Boundaries this pipeline does not gate" in doc
    assert "to_markdown" in doc
    assert "llm_mode" in doc
