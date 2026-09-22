"""Normalization contract for classification input (Classification 2.0).

Contract types only — ``NormalizedDocument`` (frozen dataclass) is the typed
shape produced from raw markdown before signal extraction, and
``TextNormalizer`` is the protocol describing the transform. No parsing or
normalization logic is implemented in M1.

Choice documented: normalization is a pure string/structure transform and is
therefore **synchronous** in the contract; can be revisited if OCR/IO work is
added later.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class NormalizedDocument:
    """Normalized document structure consumed by signal detectors.

    ``raw_text`` is the original markdown; ``headings``/``tables``/
    ``paragraphs`` are the structural views extracted from it. ``metadata``
    carries arbitrary per-document context (client type, ids, etc.).
    """

    raw_text: str
    headings: list[str]
    tables: list[str]
    paragraphs: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


class TextNormalizer(Protocol):
    """Protocol for transforms producing a ``NormalizedDocument``."""

    def normalize(self, markdown: str) -> NormalizedDocument:
        """Normalize raw ``markdown`` into a ``NormalizedDocument``.

        Contract only — no implementation is provided in M1.
        """
        ...


__all__ = ["NormalizedDocument", "TextNormalizer"]