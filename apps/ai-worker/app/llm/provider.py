"""LLM provider/model selection.

The ai-worker talks to one OpenAI-compatible endpoint today. This module owns
the "which model" decision so domain code never hard-codes providers.
"""


def resolve_model(model: str | None, default: str) -> str:
    return model or default