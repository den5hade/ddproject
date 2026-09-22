"""Artifact uploads to object storage."""

import asyncio


async def upload_bytes(s3, content: bytes, key: str, content_type: str) -> None:
    """Upload a raw blob to S3, off the event loop."""
    await asyncio.to_thread(s3.upload_bytes, content, key, content_type)


async def upload_text(s3, content: str, key: str, content_type: str) -> None:
    """Upload a text blob (UTF-8) to S3, off the event loop."""
    await upload_bytes(s3, content.encode("utf-8"), key, content_type)


async def ensure_bucket(s3, bucket_name: str) -> None:
    """Create the bucket if configured and missing, off the event loop."""
    if bucket_name:
        await asyncio.to_thread(s3.ensure_bucket)