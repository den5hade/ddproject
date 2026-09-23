"""Document artifacts: object-storage access and model keys."""

from app.artifacts.models import (
    MARKDOWN_KIND_CANONICAL,
    MARKDOWN_KIND_CLASSIFICATION,
    MARKDOWN_KIND_STRUCTURED,
    MARKDOWN_KIND_UNSTRUCTURED,
    build_markdown_key,
)
from app.artifacts.reader import download_bytes, download_text
from app.artifacts.storage import build_cloud_s3
from app.artifacts.writer import ensure_bucket, upload_bytes, upload_text

__all__ = [
    "MARKDOWN_KIND_CANONICAL",
    "MARKDOWN_KIND_CLASSIFICATION",
    "MARKDOWN_KIND_STRUCTURED",
    "MARKDOWN_KIND_UNSTRUCTURED",
    "build_cloud_s3",
    "build_markdown_key",
    "download_bytes",
    "download_text",
    "ensure_bucket",
    "upload_bytes",
    "upload_text",
]