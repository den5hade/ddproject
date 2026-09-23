"""Generic/fallback document detection signals (Classification 2.0).

Fallback detector contract: the generic class is a *scoring fallback*, not a
signal source — generic decision (``document_type=other``) results from the
scoring engine when no specialized detector accumulates enough score. This
detector therefore never emits signals.
"""

from app.classification.models import ClassificationSignal
from app.classification.normalize import NormalizedDocument
from app.classification.signals.base import SignalDetector


class GenericSignalDetector(SignalDetector):
    """Fallback detector contract — intentionally emits no signals."""

    def detect(self, document: NormalizedDocument) -> list[ClassificationSignal]:
        return []


__all__ = ["GenericSignalDetector"]