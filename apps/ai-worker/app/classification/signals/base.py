"""Base types for classification signals (Classification 2.0).

Concrete signals for each canonical class live in this package (laboratory,
appointment, prescription, generic). ``Signal`` is the legacy placeholder
base; ``SignalDetector`` is the contract protocol every per-type detector
must satisfy. Shared helpers for literal/regex occurrence counting and
markdown-table cell extraction (used by the concrete detectors) live here so
all detectors match the same canonical form.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol

from app.classification.models import ClassificationSignal

if TYPE_CHECKING:
    from app.classification.normalize import NormalizedDocument


class Signal:
    """A single, inspectable reason a document hinted at a document type."""


class SignalDetector(Protocol):
    """Protocol for detectors that surface classification signals.

    Implementations inspect a normalized document and return the list of
    signals they contribute; scoring consumes these signals. Only *matched*
    signals are emitted: ``matched=True`` with ``matches`` = occurrence count.
    Weight classes come from ``scoring`` (strong ±5 / medium ±3 / weak ±1 /
    contradicting −4).
    """

    def detect(self, document: NormalizedDocument) -> list[ClassificationSignal]:
        """Detect classification signals in ``document``."""
        ...


def _clean_cell(cell: str) -> str:
    """Strip table-cell chrome (pipes, bold markers, colons, spaces)."""
    return cell.strip().strip("*").strip().strip(":").strip()


def _table_rows(tables: list[str]) -> Iterable[list[str]]:
    """Yield cleaned cell rows for every markdown table block."""
    for block in tables:
        for line in block.splitlines():
            content = line.strip().strip("|")
            if content:
                yield [_clean_cell(cell) for cell in content.split("|")]


def _table_headers(tables: list[str]) -> Iterable[list[str]]:
    """Yield the cleaned first row of every markdown table block."""
    for block in tables:
        lines = [line.strip().strip("|") for line in block.splitlines()]
        lines = [line for line in lines if line]
        if lines:
            yield [_clean_cell(cell) for cell in lines[0].split("|")]


def count_literal(patterns: Iterable[str], *texts: str) -> int:
    """Count total occurrences of literal ``patterns`` across ``texts``."""
    total = 0
    for pattern in patterns:
        for text in texts:
            total += text.count(pattern)
    return total


def count_regex(patterns: Iterable[str], *texts: str) -> int:
    """Count total regex matches of ``patterns`` across ``texts``."""
    total = 0
    for pattern in patterns:
        compiled = re.compile(pattern)
        for text in texts:
            total += len(compiled.findall(text))
    return total


__all__ = ["Signal", "SignalDetector"]