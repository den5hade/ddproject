from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.ai_client import AIClient
from app.config import Settings


@pytest.fixture
def ai_client():
    settings = Settings(ai_api_key="test-key")
    return AIClient(settings)


def _mock_create(content, usage=None):
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    mock_create = AsyncMock(return_value=response)
    return mock_create, response


@pytest.mark.asyncio
async def test_extract_text_from_image(ai_client):
    mock_create, _ = _mock_create("# Extracted text")
    with patch.object(ai_client._client.chat.completions, "create", new=mock_create):
        result = await ai_client.extract_text_from_image(
            image_bytes=b"\x89PNG\r\n\x1a\nfake-png",
            system_prompt="Extract text",
        )

        assert result == "# Extracted text"
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_extract_text_from_image_sends_image(ai_client):
    image_bytes = b"\x89PNG\r\n\x1a\nrest-of-png"
    mock_create, _ = _mock_create("ok")
    with patch.object(ai_client._client.chat.completions, "create", new=mock_create):
        await ai_client.extract_text_from_image(image_bytes=image_bytes, system_prompt="p")

        call_kwargs = mock_create.call_args.kwargs
        user_content = call_kwargs["messages"][1]["content"]
        image_url = user_content[1]["image_url"]["url"]
        assert image_url.startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_extract_canonical_returns_json_object(ai_client):
    payload = '{"type": "generic", "fields": {"note": "x"}}'
    mock_create, _ = _mock_create(payload)
    with patch.object(ai_client._client.chat.completions, "create", new=mock_create):
        result = await ai_client.extract_canonical(
            markdown="raw text",
            system_prompt="Extract JSON",
        )

        assert result.content == payload
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_extract_canonical_strips_code_fence(ai_client):
    payload = '{"type": "generic", "fields": {"note": "x"}}'
    mock_create, _ = _mock_create(f"```json\n{payload}\n```")
    with patch.object(ai_client._client.chat.completions, "create", new=mock_create):
        result = await ai_client.extract_canonical(
            markdown="raw text",
            system_prompt="Extract JSON",
        )

        assert result.content == payload


@pytest.mark.asyncio
async def test_extract_canonical_captures_usage(ai_client):
    payload = '{"type": "generic", "fields": {"note": "x"}}'
    mock_create, _ = _mock_create(
        payload,
        usage=MagicMock(prompt_tokens=10, completion_tokens=5),
    )
    with patch.object(ai_client._client.chat.completions, "create", new=mock_create):
        result = await ai_client.extract_canonical(
            markdown="raw text",
            system_prompt="Extract JSON",
        )

        assert result.usage == {"input": 10, "output": 5, "total": 15}
