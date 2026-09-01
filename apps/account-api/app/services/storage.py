import asyncio
import json
import logging
from uuid import UUID

from storage import (
    MARKDOWN_KIND_CANONICAL,
    MARKDOWN_KIND_STRUCTURED,
    MARKDOWN_KIND_UNSTRUCTURED,
    CloudS3,
    StorageConfig,
    build_key,
    markdown_key,
    original_filename_for,
)

from app.core.config import settings

logger = logging.getLogger("account_api.storage")

DOWNLOAD_URL_TTL = 900


class StorageUnavailableError(Exception):
    """Object storage is not configured; presigned URLs cannot be issued."""


class StorageService:
    """Thin adapter over ``pdf-storage`` so account-api tests can fake S3."""

    def __init__(self, s3: CloudS3 | None) -> None:
        self._s3 = s3

    @classmethod
    def from_settings(cls) -> "StorageService":
        config = StorageConfig(
            s3_endpoint_url=settings.s3_endpoint_url,
            s3_key_id=settings.s3_key_id,
            s3_key_secret=settings.s3_key_secret,
            s3_bucket_name=settings.s3_bucket_name,
            s3_region=settings.s3_region,
            s3_tenant_id=settings.s3_tenant_id,
        )
        if not (config.s3_key_id and config.s3_bucket_name):
            logger.warning("s3_not_configured; download links will be unavailable")
            return cls(None)
        return cls(CloudS3(config))

    @staticmethod
    def tenant_id() -> str:
        return settings.s3_tenant_id or "default"

    def object_key(
        self,
        *,
        patient_id: UUID,
        document_id: UUID,
        version_id: UUID,
        filename: str,
    ) -> str:
        return build_key(
            self.tenant_id(),
            patient_id,
            document_id,
            version_id,
            filename,
        )

    def canonical_filename(self, mime_type: str) -> str:
        return original_filename_for(mime_type)

    def markdown_object_key(
        self,
        *,
        patient_id: UUID,
        document_id: UUID,
        version_id: UUID,
        kind: str,
    ) -> str:
        if kind not in (
            MARKDOWN_KIND_UNSTRUCTURED,
            MARKDOWN_KIND_STRUCTURED,
            MARKDOWN_KIND_CANONICAL,
        ):
            raise ValueError(f"unknown markdown kind: {kind}")
        return markdown_key(
            tenant_id=self.tenant_id(),
            patient_id=patient_id,
            document_id=document_id,
            version_id=version_id,
            kind=kind,
        )

    def canonical_object_key(
        self,
        *,
        patient_id: UUID,
        document_id: UUID,
        version_id: UUID,
    ) -> str:
        return self.markdown_object_key(
            patient_id=patient_id,
            document_id=document_id,
            version_id=version_id,
            kind=MARKDOWN_KIND_CANONICAL,
        )

    async def download_text(self, key: str) -> str | None:
        """Download a UTF-8 text file from S3.

        Returns ``None`` when object storage is not configured or the object
        does not exist, so callers can treat a missing blob as a graceful
        absence rather than an error.
        """
        if self._s3 is None:
            return None
        try:
            content_bytes = await asyncio.to_thread(self._s3.download_bytes, key)
        except Exception:
            logger.debug("download_text_missing key=%s", key)
            return None
        return content_bytes.decode("utf-8")

    async def download_json(self, key: str) -> dict | None:
        """Download a JSON file from S3 and parse it.

        Returns ``None`` when object storage is not configured or the object
        does not exist, so callers can treat a missing file as a graceful
        absence rather than an error.
        """
        text = await self.download_text(key)
        if text is None:
            return None
        return json.loads(text)

    def object_exists(self, key: str) -> bool:
        if self._s3 is None:
            return False
        return self._s3.head(key) is not None

    def download_url(
        self,
        key: str,
        filename: str | None = None,
        expires_in: int = DOWNLOAD_URL_TTL,
    ) -> str:
        if self._s3 is None:
            raise StorageUnavailableError("object storage is not configured")
        return self._s3.presigned_get(key, expires_in=expires_in, filename=filename)
