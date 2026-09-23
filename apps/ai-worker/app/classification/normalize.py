"""Normalization for classification input (Classification 2.0).

M1 defined the contract types (``NormalizedDocument`` frozen dataclass and the
``TextNormalizer`` protocol). M2 adds the concrete ``MarkdownNormalizer`` that
transforms raw marker markdown into a ``NormalizedDocument``: unicode
normalization (NFC), case folding, whitespace collapse and punctuation
normalization for deterministic matching, plus markdown structure parsing into
headings / table blocks / paragraphs.

Markdown structure is **preserved, not stripped** (design-spec §15): classifiers
keep access to ``headings``, ``tables`` and ``paragraphs`` instead of a single
flattened string, so structural signals (table headers, key:value rows) can be
extracted later.

Normalization is a pure string/structure transform and is *synchronous*;
revisit only if OCR/IO work is added later.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol

# Pre-normalized punctuation variants collapsed to a canonical form so that
# OCR quirks (different dashes, curly quotes, nbsp) do not break matching.
_PUNCT_MAP = {
    "\u00a0": " ",
    "\u2007": " ",
    "\u202f": " ",
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
    "\ufeff": "",
}

_WS_RE = re.compile(r"\s+")
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")


@dataclass(frozen=True)
class NormalizedDocument:
    """Normalized document structure consumed by signal detectors.

    ``raw_text`` is the fully normalized markdown (case-folded, whitespace
    flattened) ready for lexical matching. ``headings``/``tables``/
    ``paragraphs`` are the structural views extracted from it. ``metadata``
    carries per-document counts plus caller-provided context (client type,
    ids, etc.).
    """

    raw_text: str
    headings: list[str]
    tables: list[str]
    paragraphs: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


class TextNormalizer(Protocol):
    """Protocol for transforms producing a ``NormalizedDocument``."""

    def normalize(self, markdown: str) -> NormalizedDocument:
        """Normalize raw ``markdown`` into a ``NormalizedDocument``."""
        ...


def _normalize_text(text: str) -> str:
    """Apply NFC + punctuation + whitespace normalization (case preserved)."""
    text = unicodedata.normalize("NFC", text)
    for source, target in _PUNCT_MAP.items():
        text = text.replace(source, target)
    return _WS_RE.sub(" ", text).strip()


def _canonical(text: str) -> str:
    """Fully canonical form for matching: normalized + case-folded."""
    return _normalize_text(text).casefold()


def _is_table_line(line: str) -> bool:
    """A markdown table row: begins and ends with a pipe (after whitespace)."""
    return bool(_TABLE_LINE_RE.match(line))


class MarkdownNormalizer(TextNormalizer):
    """Concrete :class:`TextNormalizer` for marker markdown (M2)."""

    def normalize(
        self,
        markdown: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> NormalizedDocument:
        """Normalize ``markdown`` into a ``NormalizedDocument``.

        Structure parsing rules:

        * heading lines (``# …``) become ``headings`` entries;
        * contiguous pipe-table lines become whole ``tables`` blocks
          (each block is a single multi-line string);
        * remaining non-empty content forms ``paragraphs`` (a block of
          consecutive lines joined with spaces).

        ``raw_text`` is the canonical (case-folded) form of the whole input;
        ``metadata`` gains ``table_count``/``heading_count``/``paragraph_count``
        alongside any caller-supplied keys.
        """
        text = markdown or ""
        headings: list[str] = []
        tables: list[str] = []
        paragraphs: list[str] = []
        para_buffer: list[str] = []
        table_buffer: list[str] = []

        def flush_paragraph() -> None:
            if para_buffer:
                paragraphs.append(" ".join(para_buffer))
                para_buffer.clear()

        def flush_table() -> None:
            if table_buffer:
                tables.append("\n".join(table_buffer))
                table_buffer.clear()

        for line in text.splitlines():
            stripped = _normalize_text(line)

            if _is_table_line(line):
                flush_paragraph()
                table_buffer.append(_canonical(line))
                continue

            flush_table()
            heading = _HEADING_RE.match(line)
            if heading:
                flush_paragraph()
                headings.append(_canonical(heading.group(2)))
            elif stripped:
                para_buffer.append(_canonical(line))
            else:
                flush_paragraph()

        flush_paragraph()
        flush_table()

        meta = dict(metadata or {})
        meta.setdefault("table_count", len(tables))
        meta.setdefault("heading_count", len(headings))
        meta.setdefault("paragraph_count", len(paragraphs))

        return NormalizedDocument(
            raw_text=_canonical(text),
            headings=headings,
            tables=tables,
            paragraphs=paragraphs,
            metadata=meta,
        )


__all__ = ["MarkdownNormalizer", "NormalizedDocument", "TextNormalizer"]