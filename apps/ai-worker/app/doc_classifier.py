"""Heuristic, offline classification of the canonical document type.

The ai-worker needs a canonical schema before asking the LLM to structure a
document. Instead of relying solely on the client-declared ``document_type``
(which defaults to ``other`` and downgrades real reports to ``generic``), we
inspect the extracted markdown text for cheap, content-based signals.

This classifier is deterministic and makes no LLM/API calls, so it adds no
cost. The client-declared type is used only as a secondary hint.
"""

_LAB_KEYWORDS = (
    "результаты лабораторных исследов",
    "лабораторное исследование",
    "биохимический анализ",
    "общий анализ крови",
    "скорость оседания эритроцитов",
    "референтный диапазон",
)

_PRESCRIPTION_KEYWORDS = (
    "рецепт",
    "назначение",
    "дозировка",
    "принимат",
    "таблет",
    "раствор для",
)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def classify_document_type(markdown: str, client_type: str | None = None) -> str:
    """Return a canonical prompt key (``laboratory``/``prescription``/``default``).

    ``client_type`` may be an account-api ``DocumentType`` value
    (``lab_result``, ``prescription``, ...) or ``None``.

    An explicitly declared recognized type wins; otherwise the markdown content
    is inspected and the result falls back to ``default``.
    """
    text = markdown or ""

    if client_type:
        normalized = (client_type or "").lower()
        if normalized == "lab_result":
            return "laboratory"
        if normalized == "prescription":
            return "prescription"

    if _contains_any(text, _LAB_KEYWORDS):
        return "laboratory"
    if _contains_any(text, _PRESCRIPTION_KEYWORDS):
        return "prescription"

    return "default"
