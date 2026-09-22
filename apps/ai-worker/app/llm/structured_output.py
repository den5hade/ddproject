"""Structured-output helpers for LLM completions.

Qwen reasoning models can burn their whole token budget on chain-of-thought and
never emit the final JSON, so structured canonical extraction disables thinking
via provider chat-template kwargs (cloud.ru forwards ``extra_body``).
"""

_JSON_EXTRACTION_EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}


def json_response_format() -> dict:
    """OpenAI-compatible ``response_format`` that requests a JSON object."""
    return {"type": "json_object"}


def json_extraction_extra_body() -> dict:
    """``extra_body`` that disables reasoning-model thinking for extraction."""
    return dict(_JSON_EXTRACTION_EXTRA_BODY)