"""OpenAI-compatible LLM client: vision OCR + structured JSON extraction."""

import base64
import json
import logging
import re
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from app.config.settings import Settings
from app.llm.exceptions import NoJsonError
from app.llm.structured_output import json_extraction_extra_body, json_response_format
from app.llm.token_usage import usage_to_dict

logger = logging.getLogger(__name__)

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass
class ExtractionResult:
    """Structured extraction output: raw JSON string plus LLM token usage."""

    content: str
    usage: dict = field(default_factory=dict)


def _media_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(_PNG_MAGIC):
        return "image/png"
    if image_bytes.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    return "image/png"


class AIClient:
    """OpenAI-compatible client for cloud.ru AI models."""

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncOpenAI(
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
        )
        self._default_model = settings.ai_model
        self._max_tokens = settings.ai_max_tokens

    async def extract_text_from_image(
        self,
        image_bytes: bytes,
        system_prompt: str,
        model: str | None = None,
        temperature: float = 0.1,
    ) -> str:
        """Extract text from an image as markdown using a vision model."""
        image_data_url = (
            f"data:{_media_type(image_bytes)};base64,"
            f"{base64.b64encode(image_bytes).decode('utf-8')}"
        )

        response = await self._client.chat.completions.create(
            model=model or self._default_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Extract all text from this document image "
                                "and format it as clean markdown."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data_url},
                        },
                    ],
                },
            ],
            temperature=temperature,
            max_tokens=self._max_tokens,
        )

        return response.choices[0].message.content or ""

    @staticmethod
    def _extract_json(content: str) -> str:
        """Return a candidate JSON payload from a response, stripping code fences.

        If the model returns a JSON object wrapped in ```json fences the
        fences are stripped; otherwise any leading/trailing prose around a
        balanced ``{...}`` block is cut away. Returns an empty string when no
        JSON object can be found, so callers treat prose-only replies as a
        failed/empty response instead of forwarding them downstream.
        """
        if not content:
            return ""
        match = _JSON_BLOCK_RE.search(content)
        if match:
            return match.group(1)
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end > start:
            return content[start : end + 1]
        return ""

    @classmethod
    def _candidate_json(cls, message) -> str | None:
        """Best JSON object from a response message, or ``None`` if not JSON.

        Combines the reasoning fallback and prose trimming with a hard check
        that the result actually parses as a JSON object.
        """
        raw = cls._extract_json(cls._message_text(message))
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(parsed, dict):
            return None
        return raw

    @staticmethod
    def _message_text(message) -> str:
        """Best available assistant text: ``content``, else reasoning output.

        Qwen reasoning models may return the answer in ``reasoning_content``
        (standard) or ``reasoning`` (legacy) with ``content`` left empty, so we
        fall back to those fields when ``content`` is blank.
        """
        content = (message.content or "").strip()
        if content:
            return content
        for attr in ("reasoning_content", "reasoning"):
            value = getattr(message, attr, None)
            if value:
                return str(value).strip()
        return ""

    @staticmethod
    def _canonical_messages(markdown: str, system_prompt: str) -> list[dict]:
        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Extract the canonical JSON from this document markdown:\n\n{markdown}",
            },
        ]

    async def extract_canonical(
        self,
        markdown: str,
        system_prompt: str,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> ExtractionResult:
        """Extract a canonical JSON object from document markdown.

        Requests a strict JSON object from the model (with thinking disabled,
        so reasoning tokens don't starve the answer) and captures usage.
        If the model replies without a parseable JSON object (empty content,
        prose-only, reasoning-leaked text, or malformed JSON), a single retry
        drops ``response_format`` and lets ``_candidate_json`` recover the
        object from free-form text. If both attempts fail a ``NoJsonError`` is
        raised so the caller can fail the job with a clear message.
        """
        messages = self._canonical_messages(markdown, system_prompt)
        response = await self._client.chat.completions.create(
            model=model or self._default_model,
            messages=messages,
            temperature=temperature,
            max_tokens=self._max_tokens,
            response_format=json_response_format(),
            extra_body=json_extraction_extra_body(),
        )
        content = self._candidate_json(response.choices[0].message)
        usage = usage_to_dict(response)

        if content is not None:
            return ExtractionResult(content=content, usage=usage)

        logger.warning(
            "canonical_no_json retry without response_format model=%s",
            model or self._default_model,
        )
        response = await self._client.chat.completions.create(
            model=model or self._default_model,
            messages=messages,
            temperature=temperature,
            max_tokens=self._max_tokens,
            extra_body=json_extraction_extra_body(),
        )
        content = self._candidate_json(response.choices[0].message)
        usage = usage_to_dict(response)

        if content is None:
            raise NoJsonError("model returned no parseable canonical JSON on either attempt")

        return ExtractionResult(content=content, usage=usage)