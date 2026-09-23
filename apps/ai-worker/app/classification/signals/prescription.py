"""Prescription document detection signals (Classification 2.0).

Signals (name convention ``prescription.<signal>``): drug_terms (лексical:
рецепт/назначение/препарат/лекарственное средство/таблетки/…), dosage_frequency
(дозировка/принимать/курс/раз в день/перед едой/…), struct_medication_headers
(structural table headers declaring a drug/knznacen list). Keyword lists follow
SUM.md §12 and the legacy keyword classifier; calibration is M3 evaluation work.
"""

from app.classification.models import ClassificationSignal
from app.classification.normalize import NormalizedDocument
from app.classification.scoring import WEIGHT_MEDIUM, WEIGHT_STRONG
from app.classification.signals.base import (
    SignalDetector,
    _table_headers,
    count_literal,
)

_DRUG_TERMS = (
    "рецепт",
    "рецептурн",
    "назнач",
    "препарат",
    "лекарственн",
    "лекарство",
    "лекарственные средства",
    "таблетк",
    "таблет",
    "капсул",
    "раствор для",
    "суспенз",
    "мазь",
    "гель",
    "сироп",
    "драже",
    "ампул",
    "упаковк",
    "флакон",
    "порошок",
    "свечи",
    "суппозитори",
)

_DOSAGE_FREQUENCY_PHRASES = (
    "дозировк",
    "доза",
    "принимат",
    "прием внутрь",
    "внутрь",
    "раз в день",
    "раза в день",
    "в сутки",
    "курс",
    "перед едой",
    "после еды",
    "во время еды",
    "запивать",
)

_MEDICATION_HEADER_TERMS = ("препарат", "назначение", "лекарственн")


class PrescriptionSignalDetector(SignalDetector):
    """Detector for prescription-document signals (matching: canonical text)."""

    def detect(self, document: NormalizedDocument) -> list[ClassificationSignal]:
        signals: list[ClassificationSignal] = []
        raw = document.raw_text

        drugs = count_literal(_DRUG_TERMS, raw)
        if drugs:
            signals.append(
                ClassificationSignal(
                    name="prescription.drug_terms",
                    weight=WEIGHT_STRONG,
                    matched=True,
                    matches=drugs,
                )
            )

        dosage = count_literal(_DOSAGE_FREQUENCY_PHRASES, raw)
        if dosage:
            signals.append(
                ClassificationSignal(
                    name="prescription.dosage_frequency",
                    weight=WEIGHT_MEDIUM,
                    matched=True,
                    matches=dosage,
                )
            )

        header_blocks = 0
        for header in _table_headers(document.tables):
            if any(
                term in cell
                for cell in header
                for term in _MEDICATION_HEADER_TERMS
            ):
                header_blocks += 1
        if header_blocks:
            signals.append(
                ClassificationSignal(
                    name="prescription.struct_medication_headers",
                    weight=WEIGHT_MEDIUM,
                    matched=True,
                    matches=header_blocks,
                )
            )

        return signals


__all__ = ["PrescriptionSignalDetector"]