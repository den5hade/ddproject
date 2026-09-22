"""Token usage capture and cost aggregation for LLM completions."""


def usage_to_dict(response) -> dict:
    """Best-effort {input, output, total} token usage from a completion response."""
    usage_raw = getattr(response, "usage", None)
    if usage_raw is None:
        return {}
    tokens_in = getattr(usage_raw, "prompt_tokens", 0) or 0
    tokens_out = getattr(usage_raw, "completion_tokens", 0) or 0
    return {
        "input": tokens_in,
        "output": tokens_out,
        "total": tokens_in + tokens_out,
    }