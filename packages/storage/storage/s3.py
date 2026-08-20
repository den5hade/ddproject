import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("pdf_storage")

ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/tiff",
    }
)


class StorageConfig(BaseSettings):
    """S3-compatible storage credentials; env vars are the same as account-api."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    s3_endpoint_url: str = ""
    s3_key_id: str = ""
    s3_key_secret: str = ""
    s3_bucket_name: str = ""
    s3_region: str = ""
    s3_tenant_id: str = ""


class CloudS3:
    """Thin synchronous wrapper over a boto3 S3 client.

    Safe to call from async code via ``asyncio.to_thread``; presigned URL
    generation is local (no network) and can be called directly.
    """

    def __init__(self, config: StorageConfig) -> None:
        self._config = config
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            # Cloud.ru S3 expects the access key in "<tenant_id>:<key_id>" format.
            access_key_id = self._config.s3_key_id
            if self._config.s3_tenant_id and not access_key_id.startswith(
                self._config.s3_tenant_id
            ):
                access_key_id = f"{self._config.s3_tenant_id}:{access_key_id}"
            session = boto3.Session(
                aws_access_key_id=access_key_id,
                aws_secret_access_key=self._config.s3_key_secret,
                region_name=self._config.s3_region,
            )
            self._client = session.client(
                "s3",
                endpoint_url=self._config.s3_endpoint_url or None,
            )
        return self._client

    def ensure_bucket(self) -> None:
        """Create the configured bucket when it does not exist yet (idempotent)."""
        bucket = self._config.s3_bucket_name
        if not bucket:
            raise RuntimeError("s3_bucket_name is not configured")
        try:
            self.client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code == 404:
                self.client.create_bucket(Bucket=bucket)
                logger.info("s3_bucket_created bucket=%s", bucket)
            else:
                raise

    def head(self, key: str) -> dict[str, Any] | None:
        """Return the object metadata or ``None`` when the key does not exist."""
        try:
            response = self.client.head_object(Bucket=self._config.s3_bucket_name, Key=key)
            keys = ("ContentLength", "ETag", "ContentType")
            return {k: response[k] for k in keys if k in response}
        except ClientError as exc:
            code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code == 404:
                return None
            raise

    def upload_file(
        self,
        local_path: str,
        key: str,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        extra_args: dict[str, Any] = {}
        if content_type:
            extra_args["ContentType"] = content_type
        if metadata:
            extra_args["Metadata"] = metadata
        self.client.upload_file(
            local_path,
            self._config.s3_bucket_name,
            key,
            ExtraArgs=extra_args or None,
        )
        logger.info("s3_uploaded key=%s size=%s", key, _file_size(local_path))

    def upload_bytes(
        self,
        data: bytes,
        key: str,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        put_kwargs: dict[str, Any] = {}
        if content_type:
            put_kwargs["ContentType"] = content_type
        if metadata:
            put_kwargs["Metadata"] = metadata
        self.client.put_object(
            Bucket=self._config.s3_bucket_name,
            Key=key,
            Body=data,
            **put_kwargs,
        )
        logger.info("s3_uploaded key=%s size=%s", key, len(data))

    def download_file(self, key: str, local_path: str) -> None:
        self.client.download_file(self._config.s3_bucket_name, key, local_path)

    def delete_object(self, key: str) -> None:
        self.client.delete_object(Bucket=self._config.s3_bucket_name, Key=key)
        logger.info("s3_deleted key=%s", key)

    def presigned_put(self, key: str, expires_in: int = 900) -> str:
        return self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._config.s3_bucket_name, "Key": key},
            ExpiresIn=expires_in,
        )

    def presigned_get(self, key: str, expires_in: int = 900, filename: str | None = None) -> str:
        params: dict[str, Any] = {
            "Bucket": self._config.s3_bucket_name,
            "Key": key,
        }
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        return self.client.generate_presigned_url("get_object", Params=params, ExpiresIn=expires_in)


def _file_size(local_path: str) -> int:
    return os.path.getsize(local_path)
