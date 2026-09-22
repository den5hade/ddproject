"""Classification service interface contract (Classification 2.0).

Defines the pipeline integration point for document classification:
``ClassificationService.classify`` (contract only, no implementation in M1).
Real detectors/scoring engines arrive in later milestones; this module only
locks the method signature and return type.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.classification.models import ClassificationResult

if TYPE_CHECKING:
    from app.classification.normalize import NormalizedDocument
    from app.pipeline.context import ProcessingContext


class ClassificationService(Protocol):
    """Protocol for any service that classifies a normalized document."""

    async def classify(
        self,
        document: NormalizedDocument,
        context: ProcessingContext,
    ) -> ClassificationResult:
        """Classify ``document`` within ``context`` and return the result.

        Contract only — no implementation is provided in M1.
        """
        ...


class ClassificationServiceBase(ClassificationService):
    """Base stub for future classification service implementations.

    Instantiation raises ``NotImplementedError``: the service is contract-only
    until detection/scoring logic is implemented in a later milestone.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "ClassificationService implementations arrive after the M1 contract."
        )


__all__ = ["ClassificationService", "ClassificationServiceBase"]