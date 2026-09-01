from storage.keys import (
    build_key,
    markdown_artifact_filename,
    markdown_key,
    original_filename_for,
)
from storage.s3 import ALLOWED_MIME_TYPES, CloudS3, StorageConfig

MARKDOWN_KIND_UNSTRUCTURED = "unstructured"
MARKDOWN_KIND_STRUCTURED = "structured"
MARKDOWN_KIND_CANONICAL = "canonical"

__all__ = [
    "ALLOWED_MIME_TYPES",
    "CloudS3",
    "MARKDOWN_KIND_CANONICAL",
    "MARKDOWN_KIND_STRUCTURED",
    "MARKDOWN_KIND_UNSTRUCTURED",
    "StorageConfig",
    "build_key",
    "markdown_artifact_filename",
    "markdown_key",
    "original_filename_for",
]


async def upload_markdown(
    s3: CloudS3,
    key: str,
    content: str,
    content_type: str = "text/markdown",
) -> None:
    """Upload markdown content to S3 (runs the sync upload in a worker thread)."""
    import asyncio

    await asyncio.to_thread(
        s3.upload_bytes,
        content.encode("utf-8"),
        key,
        content_type,
    )


async def download_markdown(s3: CloudS3, key: str) -> str:
    """Download markdown content from S3 and decode it as UTF-8."""
    import asyncio

    content_bytes = await asyncio.to_thread(s3.download_bytes, key)
    return content_bytes.decode("utf-8")


async def upload_json(s3: CloudS3, key: str, content: str) -> None:
    """Upload JSON content to S3 (runs the sync upload in a worker thread)."""
    import asyncio

    await asyncio.to_thread(
        s3.upload_bytes,
        content.encode("utf-8"),
        key,
        "application/json",
    )


async def download_json(s3: CloudS3, key: str) -> str:
    """Download JSON content from S3 and decode it as UTF-8.

    Returns the raw JSON string; callers should use ``json.loads`` to parse.
    This keeps the storage layer free of ``json`` dependency.
    """
    import asyncio

    content_bytes = await asyncio.to_thread(s3.download_bytes, key)
    return content_bytes.decode("utf-8")
