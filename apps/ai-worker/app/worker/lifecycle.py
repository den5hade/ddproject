"""Worker process lifecycle helpers."""

from app.artifacts.writer import ensure_bucket
from app.config.settings import Settings


async def ensure_storage(s3, settings: Settings) -> None:
    """Create the configured S3 bucket up front so the worker never races it."""
    await ensure_bucket(s3, settings.s3_bucket_name)