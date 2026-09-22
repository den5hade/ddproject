"""Artifact downloads from object storage."""

import asyncio


async def download_bytes(s3, key: str) -> bytes:
    """Download a blob from S3, off the event loop."""
    return await asyncio.to_thread(s3.download_bytes, key)


async def download_text(s3, key: str, encoding: str = "utf-8") -> str:
    """Download a blob from S3 and decode it as text."""
    blob = await download_bytes(s3, key)
    return blob.decode(encoding)