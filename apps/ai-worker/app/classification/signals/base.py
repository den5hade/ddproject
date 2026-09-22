"""Base types for classification signals (Classification 2.0).

Concrete signals for each canonical class live in this package (laboratory,
appointment, prescription, generic). ``Signal`` is the legacy placeholder
base; ``SignalDetector`` is the contract protocol every per-type detector
must satisfy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.classification.models import ClassificationSignal

if TYPE_CHECKING:
    from app.classification.normalize import NormalizedDocument


class Signal:
    """A single, inspectable reason a document hinted at a document type."""


class SignalDetector(Protocol):
    """Protocol for detectors that surface classification signals.

    Implementations inspect a normalized document and return the list of
    signals they contribute; scoring (Phase 6) consumes these signals.
    """

    def detect(self, document: NormalizedDocument) -> list[ClassificationSignal]:
        """Detect classification signals in ``document``.

        Contract only — no detection logic is implemented in M1.
        """
        ...


__all__ = ["Signal", "SignalDetector"]