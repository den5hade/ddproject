"""Laboratory document detection signals (Classification 2.0).

Contract stub only — the detector conforms to ``SignalDetector`` but implements
no detection logic in M1. Intended signal categories (for the future
implementation): laboratory_section, reference_range, measurement_unit,
result_value, laboratory_parameter, abnormal_flag, specimen, laboratory_number,
biomarker, hematology_marker.
"""

from app.classification.models import ClassificationSignal
from app.classification.normalize import NormalizedDocument
from app.classification.signals.base import SignalDetector


class LaboratorySignalDetector(SignalDetector):
    """Detector for laboratory-document signals (stub, M1 contract)."""

    def detect(self, document: NormalizedDocument) -> list[ClassificationSignal]:
        raise NotImplementedError("Detection logic arrives after the M1 contract.")


__all__ = ["LaboratorySignalDetector"]