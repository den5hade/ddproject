from unittest.mock import AsyncMock, MagicMock

import pytest

from storage import download_json, download_markdown, upload_json, upload_markdown


@pytest.mark.asyncio
async def test_upload_markdown_encodes_and_uploads():
    s3 = MagicMock()
    await upload_markdown(s3, "some/key/marker.md", "# Hello")
    s3.upload_bytes.assert_called_once_with(
        b"# Hello",
        "some/key/marker.md",
        "text/markdown",
    )


@pytest.mark.asyncio
async def test_upload_markdown_defaults_content_type():
    s3 = MagicMock()
    await upload_markdown(s3, "some/key/structured.md", "body")
    s3.upload_bytes.assert_called_once_with(
        b"body",
        "some/key/structured.md",
        "text/markdown",
    )


@pytest.mark.asyncio
async def test_download_markdown_decodes_utf8():
    s3 = MagicMock()
    s3.download_bytes.return_value = "# Struktura\n\nтекст".encode("utf-8")
    result = await download_markdown(s3, "some/key/structured.md")
    assert result == "# Struktura\n\nтекст"
    s3.download_bytes.assert_called_once_with("some/key/structured.md")


@pytest.mark.asyncio
async def test_upload_json_encodes_and_uploads():
    s3 = MagicMock()
    await upload_json(s3, "some/key/canonical.json", '{"type": "generic"}')
    s3.upload_bytes.assert_called_once_with(
        b'{"type": "generic"}',
        "some/key/canonical.json",
        "application/json",
    )


@pytest.mark.asyncio
async def test_download_json_decodes_utf8():
    s3 = MagicMock()
    s3.download_bytes.return_value = b'{"type": "generic"}'
    result = await download_json(s3, "some/key/canonical.json")
    assert result == '{"type": "generic"}'
    s3.download_bytes.assert_called_once_with("some/key/canonical.json")
