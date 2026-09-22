"""Prescription document detection signals (Classification 2.0).

Contract stub only — the detector conforms to ``SignalDetector`` but implements
no detection logic in M1. Intended signal categories (for the future
implementation): назначение/препарат/лекарственный, дозировка/dose/frequency/
курс/принимать, формы/единицы.
"""

from app.classification.models import ClassificationSignal
from app.classification.normalize import NormalizedDocument
from app.classification.signals.base import SignalDetector


class PrescriptionSignalDetector(SignalDetector):
    """Detector for prescription-document signals (stub, M1 contract)."""

    def detect(self, document: NormalizedDocument) -> list[ClassificationSignal]:
        raise NotImplementedError("Detection logic arrives after the M1 contract.")


__all__ = ["PrescriptionSignalDetector"]