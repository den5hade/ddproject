from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.config.settings import Settings
from app.llm import AIClient


@pytest.fixture
def ai_client():
    settings = Settings(ai_api_key="test-key")
    return AIClient(settings)


def _mock_create(content, usage=None, reasoning_content=None, reasoning=None):
    message = MagicMock()
    message.content = content
    if reasoning_content is not None:
        message.reasoning_content = reasoning_content
    else:
        delattr(message, "reasoning_content")
    if reasoning is not None:
        message.reasoning = reasoning
    else:
        delattr(message, "reasoning")
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
        assert call_kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


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


@pytest.mark.asyncio
async def test_extract_canonical_retries_without_response_format_on_empty(ai_client):
    # First strict call returns empty (model refusal), retry returns JSON.
    first_mock, _ = _mock_create("")
    second_payload = '{"type": "generic", "fields": {"note": "recovered"}}'
    second_mock, _ = _mock_create(second_payload)

    def side_effect(**kwargs):
        if "response_format" in kwargs:
            return first_mock.return_value
        return second_mock.return_value

    create = AsyncMock(side_effect=side_effect)
    with patch.object(ai_client._client.chat.completions, "create", new=create):
        result = await ai_client.extract_canonical(
            markdown="raw text",
            system_prompt="Extract JSON",
        )

        assert result.content == second_payload
    assert create.call_count == 2
    first_call, second_call = create.await_args_list
    assert first_call.kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert second_call.kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


@pytest.mark.asyncio
async def test_extract_canonical_reads_reasoning_content(ai_client):
    payload = '{"type": "generic", "fields": {"note": "reasoned"}}'
    mock_create, _ = _mock_create("", reasoning_content=payload)
    with patch.object(ai_client._client.chat.completions, "create", new=mock_create):
        result = await ai_client.extract_canonical(
            markdown="raw text",
            system_prompt="Extract JSON",
        )

        assert result.content == payload
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_extract_canonical_reads_legacy_reasoning(ai_client):
    payload = '{"type": "generic", "fields": {"note": "legacy"}}'
    mock_create, _ = _mock_create("", reasoning=payload)
    with patch.object(ai_client._client.chat.completions, "create", new=mock_create):
        result = await ai_client.extract_canonical(
            markdown="raw text",
            system_prompt="Extract JSON",
        )

        assert result.content == payload
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_extract_canonical_prefers_content_over_reasoning(ai_client):
    content_payload = '{"type": "generic", "fields": {"note": "content"}}'
    reasoning_payload = '{"type": "generic", "fields": {"note": "reasoning"}}'
    mock_create, _ = _mock_create(content_payload, reasoning_content=reasoning_payload)
    with patch.object(ai_client._client.chat.completions, "create", new=mock_create):
        result = await ai_client.extract_canonical(
            markdown="raw text",
            system_prompt="Extract JSON",
        )

        assert result.content == content_payload
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_extract_canonical_recovers_prose_wrapped_json_on_retry(ai_client):
    second_payload = '{"type": "lab_result", "fields": {"value": "recovered"}}'

    async def side_effect(**kwargs):
        if "response_format" in kwargs:
            return _mock_create("")[0].return_value
        return _mock_create(f"Here is the data:\n{second_payload}")[0].return_value

    create = AsyncMock(side_effect=side_effect)
    with patch.object(ai_client._client.chat.completions, "create", new=create):
        result = await ai_client.extract_canonical(
            markdown="raw text",
            system_prompt="Extract JSON",
        )

    assert result.content == second_payload


@pytest.mark.asyncio
async def test_extract_canonical_raises_when_both_attempts_empty(ai_client):
    create = AsyncMock(return_value=_mock_create("")[0].return_value)
    with (
        patch.object(ai_client._client.chat.completions, "create", new=create),
        pytest.raises(ValueError, match="canonical JSON"),
    ):
        await ai_client.extract_canonical(
            markdown="raw text",
            system_prompt="Extract JSON",
        )

    assert create.call_count == 2


@pytest.mark.asyncio
async def test_extract_canonical_rejects_prose_only_and_retries(ai_client):
    # The model replies with prose and no JSON object at all -- both attempts.
    create = AsyncMock(
        return_value=_mock_create("Извлечение выполнено. Данных нет.")[0].return_value
    )
    with (
        patch.object(ai_client._client.chat.completions, "create", new=create),
        pytest.raises(ValueError, match="canonical JSON"),
    ):
        await ai_client.extract_canonical(
            markdown="raw text",
            system_prompt="Extract JSON",
        )

    assert create.call_count == 2


@pytest.mark.asyncio
async def test_extract_canonical_rejects_non_object_json(ai_client):
    # JSON array parses but is not a dict -- must not be accepted.
    create = AsyncMock(return_value=_mock_create("[1, 2, 3]")[0].return_value)
    with (
        patch.object(ai_client._client.chat.completions, "create", new=create),
        pytest.raises(ValueError, match="canonical JSON"),
    ):
        await ai_client.extract_canonical(
            markdown="raw text",
            system_prompt="Extract JSON",
        )

    assert create.call_count == 2