"""Phase 6: per-fixture regression over the Classification 2.0 dataset.

Every manifest fixture must classify to its declared type/decision/subtype;
real laboratory markers must never fall back to generic or a wrong document
type (the top wrong-schema regression risk).
"""

from uuid import uuid4

import pytest
from app.classification import MarkdownNormalizer, RuleBasedClassificationService
from app.pipeline.context import ProcessingContext
from tests.support.classification_fixtures import iter_classification_fixtures

_NORMALIZER = MarkdownNormalizer()


def _context() -> ProcessingContext:
    return ProcessingContext(
        document_id=uuid4(),
        document_version_id=uuid4(),
        patient_id=uuid4(),
    )


@pytest.mark.parametrize(
    "fixture",
    iter_classification_fixtures(),
    ids=lambda fixture: fixture.file,
)
async def test_fixture_classifies_to_expected(fixture):
    service = RuleBasedClassificationService()
    doc = _NORMALIZER.normalize(fixture.path.read_text(encoding="utf-8"))
    result = await service.classify(doc, _context())

    assert result.document_type.value == fixture.expected_type
    assert result.decision.value == fixture.expected_decision
    if fixture.expected_subtype is not None:
        assert result.document_subtype == fixture.expected_subtype


async def test_real_laboratory_markers_never_misroute():
    service = RuleBasedClassificationService()
    lab_markers = [
        fixture
        for fixture in iter_classification_fixtures()
        if fixture.source == "real" and fixture.file.startswith("laboratory/")
    ]
    assert len(lab_markers) == 6
    for fixture in lab_markers:
        doc = _NORMALIZER.normalize(fixture.path.read_text(encoding="utf-8"))
        result = await service.classify(doc, _context())
        assert result.document_type.value == "laboratory", fixture.file
        assert result.decision.value == "accept", fixture.file


async def test_dataset_not_harder_than_baseline():
    fixtures = iter_classification_fixtures()
    service = RuleBasedClassificationService()
    matches = 0
    for fixture in fixtures:
        doc = _NORMALIZER.normalize(fixture.path.read_text(encoding="utf-8"))
        result = await service.classify(doc, _context())
        if result.document_type.value == fixture.expected_type:
            matches += 1
    assert matches / len(fixtures) >= 0.95