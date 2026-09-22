"""Classification signals and signal-contribution base types."""

from app.classification.signals.appointment import AppointmentSignalDetector
from app.classification.signals.base import Signal, SignalDetector
from app.classification.signals.generic import GenericSignalDetector
from app.classification.signals.laboratory import LaboratorySignalDetector
from app.classification.signals.prescription import PrescriptionSignalDetector

__all__ = [
    "AppointmentSignalDetector",
    "GenericSignalDetector",
    "LaboratorySignalDetector",
    "PrescriptionSignalDetector",
    "Signal",
    "SignalDetector",
]