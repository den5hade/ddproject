"""Contract + behavior tests for Classification 2.0 signal detectors."""

from typing import Protocol

from app.classification.models import ClassificationSignal
from app.classification.normalize import MarkdownNormalizer, NormalizedDocument
from app.classification.scoring import (
    WEIGHT_CONTRADICTING,
    WEIGHT_STRONG,
)
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

_NORMALIZER = MarkdownNormalizer()

LAB_MARKER = """## Page 1

# БЮДЖЕТНОЕ УЧРЕЖДЕНИЕ ХАНТЫ-МАНСИЙСКОГО АВТОНОМНОГО ОКРУГА - ЮГРЫ

**Лаб. номер:** 2829164

| | |
| :--- | :--- |
| **Пациент:** **ШАДЕРКИН ДЕНИС СЕРГЕЕВИЧ** | **Пол/возр.:** **М / 27.07.1984** |

### Гематологические исследования

**Общий (клинический) анализ крови**

| Параметр | Результат | Ед. изм. | Референсные значения |
| :--- | :--- | :--- | :--- |
| WBC Лейкоциты | 4,75 | 10^9/л | [4,6 - 10,2] |
| RBC Эритроциты | 5,34 | 10^12/л | [4,04 - 6,13] |
| HGB Гемоглобин | 147 | г/л | [122 - 181] |
| PLT Тромбоциты | 393 | 10^9/л | [142 - 424] |
"""

APP_MARKER = """## Page 1

07/03/2026, 09:30
Электронная регистратура Югры

# Запись успешно выполнена

| | |
| :--- | :--- |
| Номер талона: | 2026030709303211960141 |
| ФИО: | Шадеркин Денис Сергеевич |
| Специальность врача: | врач-терапевт участковый |
| ФИО врача: | Моздор Милена Игоревна |
| Кабинет: | 1 МЕЛИК-КАРАМОВА 4 |
| Дата и время: | 19 марта на 09:36 |
"""


def test_legacy_signal_placeholder_still_exportable():
    assert issubclass(Signal, object)


def test_signal_detector_is_protocol():
    assert issubclass(SignalDetector, Protocol)


def test_all_detectors_return_signal_lists():
    for klass, name in DETECTOR_PAIRS:
        assert klass.__name__ == name
        detector = klass()
        assert isinstance(detector.detect(DOCUMENT), list)


def test_detector_detect_returns_signal_list_contract():
    for klass, _ in DETECTOR_PAIRS:
        annotation = klass.detect.__annotations__["return"]
        assert annotation == list[ClassificationSignal]


def test_package_exports_detectors():
    from app.classification.signals import __all__ as signals_all

    for name in DETECTOR_NAMES:
        assert name in signals_all


# --- Behavior: sample signals (M2 Phase 2) ----------------------------------


def signal_names(signals):
    return {s.name: s for s in signals}


def test_laboratory_detector_fires_on_lab_marker():
    doc = _NORMALIZER.normalize(LAB_MARKER)
    signals = signal_names(LaboratorySignalDetector().detect(doc))
    assert "laboratory.reference_range" in signals
    assert signals["laboratory.reference_range"].matched
    assert signals["laboratory.reference_range"].matches == 1
    assert "laboratory.hematology_marker" in signals
    assert signals["laboratory.hematology_marker"].weight == WEIGHT_STRONG
    assert signals["laboratory.hematology_marker"].matches >= 3
    assert "laboratory.laboratory_parameter" in signals
    assert "laboratory.laboratory_section" in signals


def test_laboratory_measurement_unit_matches_count_is_correct():
    doc = _NORMALIZER.normalize(LAB_MARKER)
    signals = signal_names(LaboratorySignalDetector().detect(doc))
    assert "laboratory.measurement_unit" in signals
    assert signals["laboratory.measurement_unit"].matches == 4  # 10^9/л x2 + 10^12/л + г/л


def test_laboratory_detector_emits_contradicting_signal_on_appointment():
    doc = _NORMALIZER.normalize(APP_MARKER)
    signals = signal_names(LaboratorySignalDetector().detect(doc))
    assert "laboratory.appointment_evidence" in signals
    assert signals["laboratory.appointment_evidence"].weight == WEIGHT_CONTRADICTING
    assert signals["laboratory.appointment_evidence"].matches >= 3


def test_laboratory_detector_no_positive_signals_on_appointment_marker():
    doc = _NORMALIZER.normalize(APP_MARKER)
    signals = [s for s in LaboratorySignalDetector().detect(doc) if s.weight > 0]
    assert signals == []


def test_appointment_detector_fires_on_appointment_marker():
    doc = _NORMALIZER.normalize(APP_MARKER)
    signals = signal_names(AppointmentSignalDetector().detect(doc))
    assert "appointment.appointment_section" in signals
    assert signals["appointment.appointment_section"].weight == WEIGHT_STRONG
    assert "appointment.key_value_patterns" in signals
    assert signals["appointment.key_value_patterns"].weight == WEIGHT_STRONG
    assert signals["appointment.key_value_patterns"].matches >= 5
    assert "appointment.doctor_specialty" in signals
    assert "appointment.appointment_time" in signals
    assert "appointment.cabinet" in signals


def test_appointment_detector_contradicts_lab_evidence():
    doc = _NORMALIZER.normalize(LAB_MARKER)
    signals = signal_names(AppointmentSignalDetector().detect(doc))
    assert "appointment.laboratory_evidence" in signals
    assert signals["appointment.laboratory_evidence"].weight == WEIGHT_CONTRADICTING


def test_appointment_detector_no_positive_signals_on_lab_marker():
    doc = _NORMALIZER.normalize(LAB_MARKER)
    signals = [s for s in AppointmentSignalDetector().detect(doc) if s.weight > 0]
    assert signals == []


def test_prescription_detector_no_signals_on_real_markers():
    lab = _NORMALIZER.normalize(LAB_MARKER)
    appt = _NORMALIZER.normalize(APP_MARKER)
    assert PrescriptionSignalDetector().detect(lab) == []
    assert PrescriptionSignalDetector().detect(appt) == []


def test_prescription_detector_fires_on_prescription_text():
    doc = _NORMALIZER.normalize(
        "Рецепт: лекарственный препарат Амоксициллин 500 мг.\n"
        "Дозировка: принимать по 1 таблетке 3 раза в день, курс 7 дней.\n"
        "Табличка назначения прилагается."
    )
    signals = signal_names(PrescriptionSignalDetector().detect(doc))
    assert "prescription.drug_terms" in signals
    assert signals["prescription.drug_terms"].weight == WEIGHT_STRONG
    assert "prescription.dosage_frequency" in signals


def test_prescription_struct_header_detected_in_tables():
    doc = _NORMALIZER.normalize(
        "| Препарат | Дозировка |\n| :--- | :--- |\n| Амоксициллин | 500 мг |"
    )
    signals = signal_names(PrescriptionSignalDetector().detect(doc))
    assert "prescription.struct_medication_headers" in signals
    assert signals["prescription.struct_medication_headers"].matches == 1


def test_generic_detector_never_emits_signals():
    assert GenericSignalDetector().detect(_NORMALIZER.normalize("Просто текст")) == []


def test_detector_no_signals_on_unrelated_text():
    doc = _NORMALIZER.normalize(
        "Выписка из истории болезни. Состояние стабильное, рекомендации соблюдать."
    )
    assert LaboratorySignalDetector().detect(doc) == []
    assert AppointmentSignalDetector().detect(doc) == []
    assert PrescriptionSignalDetector().detect(doc) == []