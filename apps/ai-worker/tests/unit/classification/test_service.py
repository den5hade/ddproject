"""Contract + behavior tests for the Classification 2.0 service (Phase 3)."""

import inspect
from typing import Protocol
from uuid import uuid4

import pytest
from app.classification.models import (
    ClassificationConfidenceLevel,
    ClassificationDecision,
    ClassificationResult,
    DocumentType,
    LaboratorySubtype,
)
from app.classification.normalize import MarkdownNormalizer
from app.classification.service import (
    ClassificationService,
    ClassificationServiceBase,
    RuleBasedClassificationService,
)
from app.pipeline.context import ProcessingContext


def test_classification_service_is_protocol():
    assert issubclass(ClassificationService, Protocol)


def test_service_concrete_stub_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        ClassificationServiceBase()


class _MinimalService(ClassificationService):
    """Structurally conforming stub used to prove the contract is callable."""

    async def classify(self, document, context) -> ClassificationResult:
        return ClassificationResult(
            document_type="laboratory",
            confidence=1.0,
            confidence_level="high",
            decision="accept",
            reasons=[],
            signals=[],
            classifier_version="2.0.0",
        )


async def test_protocol_contract_signature_is_usable():
    service: ClassificationService = _MinimalService()
    result = await await_service(service)
    assert result.document_type == "laboratory"
    assert result.classifier_version == "2.0.0"


async def await_service(service: ClassificationService) -> ClassificationResult:
    return await service.classify(document=None, context=None)  # type: ignore[arg-type]


# --- RuleBasedClassificationService behavior (M2 Phase 3) -------------------

_NORMALIZER = MarkdownNormalizer()

LAB_MARKER = """## Page 1

# БЮДЖЕТНОЕ УЧРЕЖДЕНИЕ ... ПОЛИКЛИНИКА № 2

**Лаб. номер:** 2829164

### Гематологические исследования

**Общий (клинический) анализ крови**

| Параметр | Результат | Ед. изм. | Референсные значения |
| :--- | :--- | :--- | :--- |
| WBC Лейкоциты | 4,75 | 10^9/л | [4,6 - 10,2] |
| HGB Гемоглобин | 147 | г/л | [122 - 181] |
| PLT Тромбоциты | 393 | 10^9/л | [142 - 424] |
"""

APP_MARKER = """## Page 1

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

AMBIGUOUS_MARKER = """| | |
| :--- | :--- |
| Кабинет: | 1 МЕЛИК-КАРАМОВА 4 |
| ФИО врача: | Моздор Милена Игоревна |

Рецепт: принимать по 1 таблетке.
"""


def _context(client_type: str = "") -> ProcessingContext:
    return ProcessingContext(
        document_id=uuid4(),
        document_version_id=uuid4(),
        patient_id=uuid4(),
        client_type=client_type,
    )


async def test_rule_based_service_constructs_without_raising():
    service = RuleBasedClassificationService()
    assert service is not None


async def test_lab_marker_classifies_laboratory_hematology():
    service = RuleBasedClassificationService()
    result = await service.classify(_NORMALIZER.normalize(LAB_MARKER), _context())
    assert result.document_type == DocumentType.LABORATORY
    assert result.document_subtype == LaboratorySubtype.HEMATOLOGY.value
    assert result.decision == ClassificationDecision.ACCEPT
    assert result.confidence_level == ClassificationConfidenceLevel.HIGH
    assert result.method == "rule_score"
    assert result.classifier_version == "2.1.0"
    assert any(s.score > 0 for s in result.signals)


async def test_appointment_marker_classifies_appointment():
    service = RuleBasedClassificationService()
    result = await service.classify(_NORMALIZER.normalize(APP_MARKER), _context())
    assert result.document_type == DocumentType.APPOINTMENT
    assert result.decision == ClassificationDecision.ACCEPT
    assert result.document_subtype is None


async def test_ambiguous_document_reports_ambiguous():
    service = RuleBasedClassificationService()
    doc = _NORMALIZER.normalize(AMBIGUOUS_MARKER)
    result = await service.classify(doc, _context())
    assert result.decision == ClassificationDecision.AMBIGUOUS
    assert "ambiguous classification" in result.warnings


async def test_uninformative_document_falls_back_to_other():
    service = RuleBasedClassificationService()
    doc = _NORMALIZER.normalize("Текстовое письмо без медицинских маркеров.")
    result = await service.classify(doc, _context())
    assert result.decision == ClassificationDecision.FALLBACK
    assert result.document_type == DocumentType.OTHER


async def test_client_type_boost_recovers_low_signals():
    service = RuleBasedClassificationService()
    doc = _NORMALIZER.normalize("Текстовое письмо без медицинских маркеров.")
    without_hint = await service.classify(doc, _context())
    assert without_hint.decision == ClassificationDecision.FALLBACK

    with_hint = await service.classify(doc, _context(client_type="lab_result"))
    assert with_hint.document_type == DocumentType.LABORATORY
    assert with_hint.decision == ClassificationDecision.ACCEPT
    hint_signals = [s for s in with_hint.signals if s.name == "laboratory.client_hint"]
    assert len(hint_signals) == 1
    assert hint_signals[0].weight == 5.0


async def test_client_type_boost_maps_prescription():
    service = RuleBasedClassificationService()
    doc = _NORMALIZER.normalize("Текстовое письмо без медицинских маркеров.")
    result = await service.classify(doc, _context(client_type="prescription"))
    assert result.document_type == DocumentType.PRESCRIPTION
    assert result.decision == ClassificationDecision.ACCEPT


async def test_unknown_client_type_is_ignored():
    service = RuleBasedClassificationService()
    doc = _NORMALIZER.normalize("Текстовое письмо без медицинских маркеров.")
    result = await service.classify(doc, _context(client_type="some_report"))
    assert result.decision == ClassificationDecision.FALLBACK


def test_service_has_no_infrastructure_imports():
    import app.classification.service as service_module

    source = inspect.getsource(service_module).lower()
    import_lines = [
        line
        for line in source.splitlines()
        if line.lstrip().startswith(("import ", "from "))
    ]
    assert not any(
        "s3" in line or "rabbit" in line or "storage" in line for line in import_lines
    )