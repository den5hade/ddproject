import logging
from uuid import UUID

from storage import CloudS3, StorageConfig, build_key, original_filename_for

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

    def download_url(
        self,
        key: str,
        filename: str | None = None,
        expires_in: int = DOWNLOAD_URL_TTL,
    ) -> str:
        if self._s3 is None:
            raise StorageUnavailableError("object storage is not configured")
        return self._s3.presigned_get(key, expires_in=expires_in, filename=filename)