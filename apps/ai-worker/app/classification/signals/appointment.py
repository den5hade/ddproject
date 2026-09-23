"""Appointment document detection signals (Classification 2.0).

Signals (name convention ``appointment.<signal>``): appointment_section,
doctor_specialty, cabinet, appointment_time, key_value_patterns (structural
key:value rows in tables), plus contradictory ``appointment.laboratory_evidence``
(high-precision laboratory phrases that make an appointment reading less
likely). Phrase coverage follows SUM.md §11 and the appointment-confirmation
regression marker; calibration is M3 evaluation work.
"""

from app.classification.models import ClassificationSignal
from app.classification.normalize import NormalizedDocument
from app.classification.scoring import (
    WEIGHT_CONTRADICTING,
    WEIGHT_MEDIUM,
    WEIGHT_STRONG,
)
from app.classification.signals.base import (
    SignalDetector,
    _table_rows,
    count_literal,
    count_regex,
)

_SECTION_PHRASES = (
    "запись успешно выполнена",
    "электронная регистратура",
    "номер талона",
    "талон",
    "адрес приема",
    "регистратур",
)

_DOCTOR_SPECIALTY_PHRASES = (
    "специальность врача",
    "фио врача",
    "врач-терапевт",
    "врач-педиатр",
    "врач-хирург",
    "врач-невролог",
    "врач-кардиолог",
    "врач-дерматолог",
    "врач-оториноларинголог",
    "врач-офтальмолог",
    "врач-акушер",
    "врач-гинеколог",
    "врач-уролог",
    "врач-стоматолог",
    "врач-психиатр",
    "врач-эндокринолог",
)

_CABINET_PHRASES = ("кабинет:", "кабинет приема")

_TIME_PHRASES = ("дата и время", "время приема", "прием на")

_TIME_RE = r"\b\d{1,2}:\d{2}\b"

# Structural key:value table keys specific to appointment confirmations.
_KEY_VALUE_KEYS = (
    "номер талона",
    "фио",
    "специальность врача",
    "фио врача",
    "кабинет",
    "дата и время",
    "адрес приема",
    "медицинская организация",
    "филиал",
)

_LAB_EVIDENCE_PHRASES = (
    "референсные значения",
    "референтный диапазон",
    "общий анализ крови",
    "протокол лабораторного исследования",
    "гематологическ",
    "биохимическ",
    "параметр | результат",
)


class AppointmentSignalDetector(SignalDetector):
    """Detector for appointment-document signals (matching: canonical text)."""

    def detect(self, document: NormalizedDocument) -> list[ClassificationSignal]:
        signals: list[ClassificationSignal] = []
        raw = document.raw_text

        section = count_literal(_SECTION_PHRASES, raw)
        if section:
            signals.append(
                ClassificationSignal(
                    name="appointment.appointment_section",
                    weight=WEIGHT_STRONG,
                    matched=True,
                    matches=section,
                )
            )

        specialty = count_literal(_DOCTOR_SPECIALTY_PHRASES, raw)
        if specialty:
            signals.append(
                ClassificationSignal(
                    name="appointment.doctor_specialty",
                    weight=WEIGHT_MEDIUM,
                    matched=True,
                    matches=specialty,
                )
            )

        cabinet = count_literal(_CABINET_PHRASES, raw)
        if cabinet:
            signals.append(
                ClassificationSignal(
                    name="appointment.cabinet",
                    weight=WEIGHT_MEDIUM,
                    matched=True,
                    matches=cabinet,
                )
            )

        time_matched = count_literal(_TIME_PHRASES, raw) + count_regex(
            (_TIME_RE,), raw
        )
        if time_matched:
            signals.append(
                ClassificationSignal(
                    name="appointment.appointment_time",
                    weight=WEIGHT_MEDIUM,
                    matched=True,
                    matches=time_matched,
                )
            )

        key_value = 0
        for row in _table_rows(document.tables):
            if row and row[0] in _KEY_VALUE_KEYS:
                key_value += 1
        if key_value:
            signals.append(
                ClassificationSignal(
                    name="appointment.key_value_patterns",
                    weight=WEIGHT_STRONG,
                    matched=True,
                    matches=key_value,
                )
            )

        lab_evidence = count_literal(_LAB_EVIDENCE_PHRASES, raw)
        if lab_evidence:
            signals.append(
                ClassificationSignal(
                    name="appointment.laboratory_evidence",
                    weight=WEIGHT_CONTRADICTING,
                    matched=True,
                    matches=lab_evidence,
                )
            )

        return signals


__all__ = ["AppointmentSignalDetector"]