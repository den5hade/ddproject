"""LLM infrastructure: OpenAI-compatible provider client.

Domain code (processing, classification) depends on this package only through
``AIClient`` and never touches provider internals.
"""

from app.llm.client import AIClient, ExtractionResult
from app.llm.exceptions import LLMError, NoJsonError

__all__ = ["AIClient", "ExtractionResult", "LLMError", "NoJsonError"]