from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.domain.medical import DocumentStatus, ExtractionStatus
from app.models.document import Document, DocumentVersion
from app.models.extraction import DocumentExtraction
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.person import Person
from app.schemas.document import CanonicalResponse
from app.services.documents import DocumentService
from app.services.storage import StorageService


class FakeStorage(StorageService):
    """In-memory StorageService stub returning inline canonical + markdown blobs."""

    def __init__(self, canonical: dict | None = None, markdown: str | None = None):
        super().__init__(None)
        self._canonical = canonical
        self._markdown = markdown

    def markdown_object_key(self, *, patient_id, document_id, version_id, kind) -> str:
        filename = "canonical.json" if kind == "canonical" else f"{kind}.md"
        return (
            f"tenants/default/patients/{patient_id}/documents/{document_id}"
            f"/versions/{version_id}/{filename}"
        )

    async def download_json(self, key: str) -> dict | None:
        return self._canonical

    async def download_text(self, key: str) -> str | None:
        return self._markdown


async def _owned_document(db_session):
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
        status=DocumentStatus.COMPLETED,
    )
    db_session.add(document)
    await db_session.flush()
    version = DocumentVersion(document_id=document.id, version=1, s3_key="original.pdf")
    db_session.add(version)
    await db_session.flush()
    return patient, document, version


CANONICAL = {
    "type": "generic",
    "subtype": "generic",
    "document_date": None,
    "language": "ru",
    "fields": {"note": "some text"},
}


async def test_get_markdown_with_canonical(db_session):
    _patient, document, _version = await _owned_document(db_session)
    storage = FakeStorage(canonical=CANONICAL, markdown="---\ntype: generic\n---\nbody")
    service = DocumentService(session=db_session, publisher=None, storage=storage)

    result = await service.get_markdown(document.id)

    assert isinstance(result, CanonicalResponse)
    assert result.has_canonical is True
    assert result.canonical == CANONICAL
    assert result.canonical_key.endswith("/canonical.json")
    assert result.structured_markdown == "---\ntype: generic\n---\nbody"


async def test_get_markdown_without_canonical(db_session):
    _patient, document, _version = await _owned_document(db_session)
    service = DocumentService(session=db_session, publisher=None, storage=FakeStorage())

    result = await service.get_markdown(document.id)

    assert result.has_canonical is False
    assert result.canonical is None
    assert result.canonical_key is None
    assert result.structured_markdown is None


async def test_get_markdown_versioned(db_session):
    _patient, document, version = await _owned_document(db_session)
    other = DocumentVersion(document_id=document.id, version=2, s3_key="other.pdf")
    db_session.add(other)
    await db_session.flush()

    storage = FakeStorage(canonical=CANONICAL)
    service = DocumentService(session=db_session, publisher=None, storage=storage)

    result = await service.get_markdown(document.id, version_id=version.id)

    assert result.has_canonical is True
    assert str(version.id) in result.canonical_key


async def test_get_markdown_missing_document_raises(db_session):
    service = DocumentService(session=db_session, publisher=None, storage=FakeStorage())

    match = "document not found"
    with pytest.raises(Exception, match=match):
        await service.get_markdown(uuid4())


async def test_get_canonical_returns_latest_succeeded(db_session):
    _patient, document, version = await _owned_document(db_session)
    db_session.add(
        DocumentExtraction(
            document_id=document.id,
            document_version_id=version.id,
            schema_name="laboratory",
            schema_version="1.0.0",
            status=ExtractionStatus.SUCCEEDED,
            confidence=1.0,
            data={"type": "laboratory", "canonical_key": "k", "structured_key": "s"},
        )
    )
    await db_session.commit()

    service = DocumentService(session=db_session, publisher=None, storage=FakeStorage())
    result = await service.get_canonical(document.id)

    assert result.schema_name == "laboratory"
    assert result.schema_version == "1.0.0"
    assert result.confidence == 1.0
    assert result.data["canonical_key"] == "k"
    assert result.data["structured_key"] == "s"


async def test_get_canonical_skips_non_succeeded(db_session):
    _patient, document, version = await _owned_document(db_session)
    db_session.add(
        DocumentExtraction(
            document_id=document.id,
            document_version_id=version.id,
            schema_name="generic",
            schema_version="1.0.0",
            status=ExtractionStatus.FAILED,
            data=None,
        )
    )
    await db_session.commit()

    service = DocumentService(session=db_session, publisher=None, storage=FakeStorage())
    with pytest.raises(Exception, match="no canonical data"):
        await service.get_canonical(document.id)


async def test_get_canonical_missing_document_raises(db_session):
    service = DocumentService(session=db_session, publisher=None, storage=FakeStorage())
    with pytest.raises(Exception, match="document not found"):
        await service.get_canonical(uuid4())


def test_canonical_object_key_uses_markdown_key_internals():
    storage = StorageService(None)
    patient_id, document_id, version_id = uuid4(), uuid4(), uuid4()
    key = storage.canonical_object_key(
        patient_id=patient_id,
        document_id=document_id,
        version_id=version_id,
    )
    assert "canonical.json" in key
    assert str(patient_id) in key


async def test_download_json_returns_dict():
    s3 = MagicMock()
    s3.download_bytes.return_value = b'{"type": "generic"}'
    service = StorageService(s3)

    result = await service.download_json("some/key/canonical.json")

    assert result == {"type": "generic"}
    s3.download_bytes.assert_called_once_with("some/key/canonical.json")


async def test_download_json_returns_none_when_no_s3():
    service = StorageService(None)
    result = await service.download_json("some/key/canonical.json")
    assert result is None


async def test_download_json_returns_none_on_missing_object():
    s3 = MagicMock()
    s3.download_bytes.side_effect = Exception("NoSuchKey")
    service = StorageService(s3)

    result = await service.download_json("some/key/canonical.json")
    assert result is None


async def test_download_text_returns_string():
    s3 = MagicMock()
    s3.download_bytes.return_value = b"# body"
    service = StorageService(s3)

    result = await service.download_text("some/key/structured.md")

    assert result == "# body"


async def test_download_text_returns_none_on_missing_object():
    s3 = MagicMock()
    s3.download_bytes.side_effect = Exception("NoSuchKey")
    service = StorageService(s3)

    result = await service.download_text("some/key/structured.md")
    assert result is None
