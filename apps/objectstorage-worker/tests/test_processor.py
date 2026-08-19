import os
from uuid import uuid4

import pytest
from app.processor import StorageProcessor
from contracts.events import DocumentProcessingFailed, DocumentStored, DocumentUploadRequested


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def head(self, key: str):
        return {"ETag": "x"} if key in self.objects else None

    def upload_file(
        self, local_path: str, key: str, content_type: str | None, metadata: dict
    ) -> None:
        with open(local_path, "rb") as handle:
            self.objects[key] = handle.read()


class FakePublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    async def publish(self, routing_key: str, event) -> None:
        self.events.append((routing_key, event))


def _event(
    temp_path: str,
    *,
    mime: str = "application/pdf",
    size: int = 42,
    version_id=None,
) -> DocumentUploadRequested:
    return DocumentUploadRequested(
        event_id=uuid4(),
        document_id=uuid4(),
        document_version_id=version_id or uuid4(),
        patient_id=uuid4(),
        tenant_id="t1",
        medical_record_id=uuid4(),
        temp_path=temp_path,
        original_filename="report.pdf",
        mime_type=mime,
        size_bytes=size,
    )


@pytest.mark.asyncio
async def test_process_uploads_and_publishes_stored(tmp_path):
    staged = tmp_path / "abc.upload"
    data = b"%PDF-1.4 test"
    staged.write_bytes(data)

    s3 = FakeS3()
    pub = FakePublisher()
    processor = StorageProcessor(s3, pub, temp_dir=str(tmp_path))
    event = _event(staged.name, size=len(data))

    await processor.process(event)

    (routing, stored) = pub.events[0]
    assert routing == "document.stored"
    assert isinstance(stored, DocumentStored)
    assert stored.storage_key.startswith("tenants/t1/patients/")
    assert stored.storage_key.endswith("/original.pdf")
    assert stored.size_bytes == len(data)
    assert stored.checksum
    assert stored.storage_key in s3.objects
    assert not os.path.exists(staged)


@pytest.mark.asyncio
async def test_process_skips_when_object_already_exists(tmp_path):
    staged = tmp_path / "abc.upload"
    staged.write_bytes(b"%PDF re-delivery")
    s3 = FakeS3()
    key = "tenants/t1/patients/p/documents/d/versions/v/original.pdf"
    s3.objects[key] = b"old"
    pub = FakePublisher()
    processor = StorageProcessor(s3, pub, temp_dir=str(tmp_path))
    event = _event(staged.name, size=5)

    await processor.process(event)

    assert s3.objects[key] == b"old"  # not re-uploaded
    assert isinstance(pub.events[0][1], DocumentStored)


@pytest.mark.asyncio
async def test_process_rejects_unsupported_mime(tmp_path):
    staged = tmp_path / "bad.upload"
    staged.write_bytes(b"not a pdf")
    pub = FakePublisher()
    s3 = FakeS3()
    processor = StorageProcessor(s3, pub, temp_dir=str(tmp_path))
    event = _event(staged.name, mime="text/plain")

    await processor.process(event)

    (routing, failed) = pub.events[0]
    assert routing == "document.processing.failed"
    assert isinstance(failed, DocumentProcessingFailed)
    assert failed.error_code == "unsupported_type"
    assert not s3.objects
    assert not os.path.exists(staged)


@pytest.mark.asyncio
async def test_process_rejects_missing_file(tmp_path):
    pub = FakePublisher()
    s3 = FakeS3()
    processor = StorageProcessor(s3, pub, temp_dir=str(tmp_path))
    event = _event("does-not-exist.upload")

    await processor.process(event)

    (routing, failed) = pub.events[0]
    assert routing == "document.processing.failed"
    assert failed.error_code == "missing_file"


@pytest.mark.asyncio
async def test_process_rejects_path_traversal(tmp_path):
    outside = tmp_path.parent / "secret.upload"
    outside.write_bytes(b"outside file")
    pub = FakePublisher()
    s3 = FakeS3()
    processor = StorageProcessor(s3, pub, temp_dir=str(tmp_path))
    event = _event(f"{tmp_path.parent.absolute()}/secret.upload")

    await processor.process(event)

    assert isinstance(pub.events[0][1], DocumentProcessingFailed)
    assert not s3.objects


@pytest.mark.asyncio
async def test_sha256_computed_correctly(tmp_path):
    from app.processor import _sha256

    staged = tmp_path / "data.bin"
    staged.write_bytes(b"hello")
    digest = _sha256(str(staged))
    assert digest == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"