import base64
import re
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from app.config import Settings

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
        """Return the JSON payload from a response, stripping code fences."""
        if not content:
            return ""
        stripped = content.strip()
        if stripped.startswith("{"):
            return stripped
        match = _JSON_BLOCK_RE.search(content)
        return match.group(1) if match else stripped

    async def extract_canonical(
        self,
        markdown: str,
        system_prompt: str,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> ExtractionResult:
        """Extract a canonical JSON object from document markdown.

        Requests a strict JSON object from the model and captures token usage.
        Falls back to extracting a JSON block from the text if the model wraps
        the answer in markdown code fences.
        """
        response = await self._client.chat.completions.create(
            model=model or self._default_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Extract the canonical JSON from this document markdown:\n\n{markdown}"
                    ),
                },
            ],
            temperature=temperature,
            max_tokens=self._max_tokens,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or ""
        usage = {}
        usage_raw = getattr(response, "usage", None)
        if usage_raw is not None:
            usage = {
                "input": getattr(usage_raw, "prompt_tokens", 0),
                "output": getattr(usage_raw, "completion_tokens", 0),
                "total": int(getattr(usage_raw, "prompt_tokens", 0))
                + int(getattr(usage_raw, "completion_tokens", 0)),
            }
        return ExtractionResult(content=self._extract_json(content), usage=usage)
