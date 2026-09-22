"""Contract-level tests for Classification 2.0 signal detectors (Phase 5)."""

from typing import Protocol

import pytest
from app.classification.models import ClassificationSignal
from app.classification.normalize import NormalizedDocument
from app.classification.signals.appointment import AppointmentSignalDetector
from app.classification.signals.base import Signal, SignalDetector
from app.classification.signals.generic import GenericSignalDetector
from app.classification.signals.laboratory import LaboratorySignalDetector
from app.classification.signals.prescription import PrescriptionSignalDetector

DETECTOR_PAIRS = [
    (LaboratorySignalDetector, "LaboratorySignalDetector"),
    (AppointmentSignalDetector, "AppointmentSignalDetector"),
    (PrescriptionSignalDetector, "PrescriptionSignalDetector"),
    (GenericSignalDetector, "GenericSignalDetector"),
]

DOCUMENT = NormalizedDocument(
    raw_text="# Page 1\n\nBody",
    headings=["Page 1"],
    tables=[],
    paragraphs=["Body"],
)

DETECTOR_NAMES = {klass.__name__ for klass, _ in DETECTOR_PAIRS}


def test_legacy_signal_placeholder_still_exportable():
    assert issubclass(Signal, object)


def test_signal_detector_is_protocol():
    assert issubclass(SignalDetector, Protocol)


def test_all_detectors_conform_and_stub_detect():
    for klass, name in DETECTOR_PAIRS:
        assert klass.__name__ == name
        detector = klass()
        assert callable(detector.detect)
        with pytest.raises(NotImplementedError):
            detector.detect(DOCUMENT)


def test_detector_detect_returns_signal_list_contract():
    for klass, _ in DETECTOR_PAIRS:
        annotation = klass.detect.__annotations__["return"]
        assert annotation == list[ClassificationSignal]


def test_package_exports_detectors():
    from app.classification.signals import __all__ as signals_all

    for name in DETECTOR_NAMES:
        assert name in signals_all