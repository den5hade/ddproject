"""Laboratory document detection signals (Classification 2.0).

Signals (name convention ``laboratory.<signal>``): laboratory_section,
reference_range, measurement_unit, result_value, laboratory_parameter,
abnormal_flag, specimen, laboratory_number, biomarker, hematology_marker, plus
contradictory ``laboratory.appointment_evidence`` (high-precision appointment
phrases that make a laboratory reading less likely). Keyword lists are informed
by the real regression markers (CBC hematology, biochemistry) and are not
calibrated further in M2 (tuning is M3 evaluation work).
"""

from app.classification.models import ClassificationSignal
from app.classification.normalize import NormalizedDocument
from app.classification.scoring import (
    WEIGHT_CONTRADICTING,
    WEIGHT_MEDIUM,
    WEIGHT_STRONG,
    WEIGHT_WEAK,
)
from app.classification.signals.base import (
    SignalDetector,
    _table_headers,
    _table_rows,
    count_literal,
    count_regex,
)

_LAB_SECTION_PHRASES = (
    "гематологические исследования",
    "гематологическое исследование",
    "биохимический анализ",
    "биохимические исследования",
    "клинический анализ крови",
    "общий анализ крови",
    "протокол лабораторного исследования",
    "результаты лабораторного исследования",
    "результаты лабораторных исследований",
    "результат лабораторного исследования",
    "лабораторное исследование",
    "исследованные материалы",
)

_REFERENCE_PHRASES = (
    "референсные значения",
    "референсное значение",
    "референтный диапазон",
    "референтные значения",
    "реф. значения",
)

_UNIT_PATTERNS = (
    r"10\^9/л",
    r"10\^12/л",
    r"мкмоль/л",
    r"ммоль/л",
    r"мг/дл",
    r"мг/мл",
    r"нг/мл",
    r"г/л",
    r"г/дл",
    r"мл/мин",
    r"ед/л",
    r"ед/мл",
    r"мкат/л",
    r"фл",
    r"пг",
)

_NUMERIC_CELL_RE = r"\d+[.,]\d+"

_ABNORMAL_PHRASES = (
    "выше нормы",
    "ниже нормы",
    "выше референсного",
    "ниже референсного",
    "повышено",
    "понижено",
    "аномальный",
    "↑",
    "↓",
)

_SPECIMEN_PHRASES = (
    "кровь венозная",
    "венозная кровь",
    "сыворотк",
    "плазма крови",
    "плазме крови",
    "биоматериал",
    "исследуемый материал",
    "эритроцитарная масса",
)

_LAB_NUMBER_PHRASES = (
    "лаб. номер",
    "лабораторный номер",
    "номер заказа",
    "номер карты",
    "номер исследования",
    "номер пробы",
    "номер анализа",
)

_BIOMARKER_TERMS = (
    "аспартатаминотрансфераза",
    "аланинаминотрансфераза",
    "гамма-глутамилтрансфераза",
    "щелочная фосфатаза",
    "креатинин",
    "билирубин",
    "холестерин",
    "триглицерид",
    "глюкоза",
    "амилаза",
    "липаза",
    "мочевина",
    "мочевая кислота",
    "альбумин",
    "ферритин",
    "сывороточное железо",
    "кальций",
    "калий",
    "натрий",
    "магний",
    "хлор",
    "общий белок",
    "с-реактивный белок",
    "срб",
    "фибриноген",
    "протромбин",
    "т4 свободный",
    "тиреотропн",
    "кортизол",
    "эстрадиол",
    "прогестерон",
    "тестостерон",
    "гликированный гемоглобин",
    "альфа-амилаза",
)

_HEMATOLOGY_TERMS = (
    "wbc",
    "rbc",
    "hgb",
    "hct",
    "mcv",
    "mch",
    "mchc",
    "rdw",
    "plt",
    "mpv",
    "pdw",
    "pct",
    "лейкоциты",
    "лейкоцитов",
    "эритроциты",
    "эритроцитов",
    "тромбоциты",
    "тромбоцитов",
    "гемоглобин",
    "гематокрит",
    "нейтрофил",
    "лимфоцит",
    "моноцит",
    "эозинофил",
    "базофил",
    "ретикулоцит",
)

_MICROBIOLOGY_TERMS = (
    "посев",
    "флора",
    "микробиологическ",
    "микроорганизм",
    "микрофлор",
    "культивировани",
    "бактериолог",
    "бактериофаг",
    "антибиотик",
    "антибактериальн",
    "биоматериал",
    "биоматериала",
)

_APPOINTMENT_EVIDENCE_PHRASES = (
    "электронная регистратура",
    "запись успешно выполнена",
    "номер талона",
    "специальность врача",
    "фио врача",
    "дата и время",
    "адрес приема",
    "кабинет:",
)


class LaboratorySignalDetector(SignalDetector):
    """Detector for laboratory-document signals (matching: canonical text)."""

    def detect(self, document: NormalizedDocument) -> list[ClassificationSignal]:
        signals: list[ClassificationSignal] = []
        raw = document.raw_text
        tables = document.tables
        rows = list(_table_rows(tables))
        headers = list(_table_headers(tables))
        cells = [cell for row in rows for cell in row]

        section = count_literal(_LAB_SECTION_PHRASES, raw)
        if section:
            signals.append(
                ClassificationSignal(
                    name="laboratory.laboratory_section",
                    weight=WEIGHT_STRONG,
                    matched=True,
                    matches=section,
                )
            )

        reference = count_literal(_REFERENCE_PHRASES, raw)
        if reference:
            signals.append(
                ClassificationSignal(
                    name="laboratory.reference_range",
                    weight=WEIGHT_STRONG,
                    matched=True,
                    matches=reference,
                )
            )

        units = count_regex(_UNIT_PATTERNS, *cells) if cells else 0
        if units:
            signals.append(
                ClassificationSignal(
                    name="laboratory.measurement_unit",
                    weight=WEIGHT_MEDIUM,
                    matched=True,
                    matches=units,
                )
            )

        numeric = count_regex((_NUMERIC_CELL_RE,), *cells) if cells else 0
        if numeric >= 3:
            signals.append(
                ClassificationSignal(
                    name="laboratory.result_value",
                    weight=WEIGHT_STRONG,
                    matched=True,
                    matches=numeric,
                )
            )

        parameter_headers = 0
        for header in headers:
            has_parameter = any(
                term in cell for term in ("параметр", "показатель") for cell in header
            )
            has_result = any(
                term in cell for term in ("результат", "значение") for cell in header
            )
            if has_parameter and has_result:
                parameter_headers += 1
        if parameter_headers:
            signals.append(
                ClassificationSignal(
                    name="laboratory.laboratory_parameter",
                    weight=WEIGHT_MEDIUM,
                    matched=True,
                    matches=parameter_headers,
                )
            )

        abnormal = count_literal(_ABNORMAL_PHRASES, raw)
        if abnormal:
            signals.append(
                ClassificationSignal(
                    name="laboratory.abnormal_flag",
                    weight=WEIGHT_WEAK,
                    matched=True,
                    matches=abnormal,
                )
            )

        specimen = count_literal(_SPECIMEN_PHRASES, raw)
        if specimen:
            signals.append(
                ClassificationSignal(
                    name="laboratory.specimen",
                    weight=WEIGHT_MEDIUM,
                    matched=True,
                    matches=specimen,
                )
            )

        lab_number = count_literal(_LAB_NUMBER_PHRASES, raw)
        if lab_number:
            signals.append(
                ClassificationSignal(
                    name="laboratory.laboratory_number",
                    weight=WEIGHT_WEAK,
                    matched=True,
                    matches=lab_number,
                )
            )

        biomarker = count_literal(_BIOMARKER_TERMS, raw)
        if biomarker:
            signals.append(
                ClassificationSignal(
                    name="laboratory.biomarker",
                    weight=WEIGHT_MEDIUM,
                    matched=True,
                    matches=biomarker,
                )
            )

        hematology = count_literal(_HEMATOLOGY_TERMS, raw)
        if hematology:
            signals.append(
                ClassificationSignal(
                    name="laboratory.hematology_marker",
                    weight=WEIGHT_STRONG,
                    matched=True,
                    matches=hematology,
                )
            )

        microbiology = count_literal(_MICROBIOLOGY_TERMS, raw)
        if microbiology:
            signals.append(
                ClassificationSignal(
                    name="laboratory.microbiology_marker",
                    weight=WEIGHT_STRONG,
                    matched=True,
                    matches=microbiology,
                )
            )

        appointment_evidence = count_literal(_APPOINTMENT_EVIDENCE_PHRASES, raw)
        if appointment_evidence:
            signals.append(
                ClassificationSignal(
                    name="laboratory.appointment_evidence",
                    weight=WEIGHT_CONTRADICTING,
                    matched=True,
                    matches=appointment_evidence,
                )
            )

        return signals


__all__ = ["LaboratorySignalDetector"]