"""Contract-level tests for the Classification 2.0 service interface (Phase 3)."""

from typing import Protocol

import pytest
from app.classification.models import ClassificationResult
from app.classification.service import ClassificationService, ClassificationServiceBase


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