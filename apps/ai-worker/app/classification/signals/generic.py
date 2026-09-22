"""Generic/fallback document detection signals (Classification 2.0).

Fallback detector contract: absorbs documents that no specialized detector
claims with sufficient confidence. Contract stub only — no detection logic
in M1.
"""

from app.classification.models import ClassificationSignal
from app.classification.normalize import NormalizedDocument
from app.classification.signals.base import SignalDetector


class GenericSignalDetector(SignalDetector):
    """Fallback detector contract (stub, M1 contract)."""

    def detect(self, document: NormalizedDocument) -> list[ClassificationSignal]:
        raise NotImplementedError("Detection logic arrives after the M1 contract.")


__all__ = ["GenericSignalDetector"]