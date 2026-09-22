"""LLM infrastructure errors."""


class LLMError(Exception):
    """Base error for all LLM client failures."""


class NoJsonError(ValueError, LLMError):
    """The model returned no parseable JSON object on any attempt."""