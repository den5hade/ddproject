"""OCR stage: render page images to unstructured markdown via a vision LLM."""

import logging
import re

from app.llm import AIClient

logger = logging.getLogger(__name__)

_PAGE_MARKER_RE = re.compile(r"^## Page (\d+)", re.MULTILINE)


def count_pages(markdown: str) -> int:
    """Count rendered image pages from their ``## Page N`` markers."""
    markers = _PAGE_MARKER_RE.findall(markdown or "")
    if not markers:
        return 1
    try:
        return max(int(number) for number in markers)
    except ValueError:
        return len(markers)


class OcrEngine:
    """Convert page images into page-chunked unstructured markdown."""

    def __init__(self, ai_client: AIClient, default_model: str) -> None:
        self._ai_client = ai_client
        self._default_model = default_model

    async def to_markdown(self, images: list[bytes], prompt: dict) -> str:
        """OCR every image in page order into a single ``## Page N`` markdown doc."""
        markdown_parts: list[str] = []
        for index, image_bytes in enumerate(images):
            logger.info("processing_page page=%s total=%s", index + 1, len(images))
            text = await self._ai_client.extract_text_from_image(
                image_bytes=image_bytes,
                system_prompt=prompt["system_prompt"],
                model=prompt.get("model", self._default_model),
                temperature=prompt.get("temperature", 0.1),
            )
            markdown_parts.append(f"## Page {index + 1}\n\n{text}")
        return "\n\n---\n\n".join(markdown_parts)