"""Keyword sets and matchers that drive heuristic document classification."""

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