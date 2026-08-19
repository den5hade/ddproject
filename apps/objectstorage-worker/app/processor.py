import asyncio
import hashlib
import logging
import os
from uuid import uuid4

from contracts.events import (
    DocumentProcessingFailed,
    DocumentStored,
    DocumentUploadRequested,
)
from storage import ALLOWED_MIME_TYPES, CloudS3, build_key, original_filename_for

from app.config import settings

logger = logging.getLogger("objectstorage_worker")

_CONVERSION_JOB_TYPE = "pdf_conversion"


class StorageProcessor:
    """Normalize/validate the staged file and push it to S3 under an immutable key."""

    def __init__(
        self,
        s3: CloudS3,
        publisher,
        temp_dir: str | None = None,
    ) -> None:
        self._s3 = s3
        self._publisher = publisher
        self._temp_dir = temp_dir or settings.storage_temp_dir

    async def process(self, event: DocumentUploadRequested) -> None:
        if event.mime_type.lower() not in ALLOWED_MIME_TYPES:
            await self._fail(event, "unsupported_type", f"unsupported mime: {event.mime_type}")
            return
        if event.size_bytes > settings.max_upload_bytes:
            await self._fail(event, "too_large", "file exceeds the configured size limit")
            return

        local_path = self._resolved_path(event.temp_path)
        if not os.path.isfile(local_path):
            await self._fail(event, "missing_file", f"staged file not found: {event.temp_path}")
            return

        actual_size = os.path.getsize(local_path)
        checksum = await asyncio.to_thread(_sha256, local_path)
        filename = original_filename_for(event.mime_type)
        key = build_key(
            event.tenant_id,
            event.patient_id,
            event.document_id,
            event.document_version_id,
            filename,
        ) if event.document_version_id else ""

        if await asyncio.to_thread(self._s3.head, key):
            logger.info("object_already_stored key=%s; skipping upload", key)
        else:
            metadata = {
                "document_id": str(event.document_id),
                "version_id": str(event.document_version_id or ""),
                "patient_id": str(event.patient_id),
            }
            await asyncio.to_thread(
                self._s3.upload_file,
                local_path,
                key,
                event.mime_type,
                metadata,
            )
            logger.info("object_uploaded key=%s size=%s", key, actual_size)
        self._cleanup(local_path)
        await self._stored(event, key, actual_size, checksum)

    async def _stored(
        self, event: DocumentUploadRequested, key: str, size: int, checksum: str
    ) -> None:
        await self._publish(
            "document.stored",
            DocumentStored(
                event_id=uuid4(),
                document_id=event.document_id,
                document_version_id=event.document_version_id,
                patient_id=event.patient_id,
                storage_key=key,
                mime_type=event.mime_type,
                size_bytes=size,
                checksum=checksum,
            ),
        )

    async def _fail(
        self, event: DocumentUploadRequested, error_code: str, message: str
    ) -> None:
        logger.warning(
            "upload_rejected code=%s document_id=%s message=%s",
            error_code,
            event.document_id,
            message,
        )
        self._cleanup(self._resolved_path(event.temp_path))
        await self._publish(
            "document.processing.failed",
            DocumentProcessingFailed(
                event_id=uuid4(),
                document_id=event.document_id,
                document_version_id=event.document_version_id,
                patient_id=event.patient_id,
                job_type=_CONVERSION_JOB_TYPE,
                error_code=error_code,
                error_message=message,
            ),
        )

    async def _publish(self, routing_key: str, event) -> None:
        if self._publisher is None:
            logger.warning(
                "event_dropped routing_key=%s document_id=%s (broker unavailable)",
                routing_key,
                event.document_id,
            )
            return
        await self._publisher.publish(routing_key, event)

    def _resolved_path(self, temp_path: str) -> str:
        safe = os.path.basename(temp_path)
        return os.path.join(self._temp_dir, safe)

    def _cleanup(self, local_path: str) -> None:
        try:
            os.remove(local_path)
        except OSError:
            logger.warning("staged_file_cleanup_failed path=%s", local_path)


def _sha256(local_path: str) -> str:
    digest = hashlib.sha256()
    with open(local_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()