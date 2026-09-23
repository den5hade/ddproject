"""Classification service interface and rule-based implementation.

Defines the pipeline integration point for document classification:
``ClassificationService.classify`` (contract). ``RuleBasedClassificationService``
(M2 Phase 3) is the concrete deterministic classifier: it runs the signal
detectors over a normalized document, optionally adds the client-declared
``client_type`` boost, scores via ``RuleScoringEngine`` and assembles a
``ClassificationResult``.

The service is intentionally independent of infrastructure: it imports no S3,
RabbitMQ or storage code — persistence/publishing is orchestrated by the
pipeline (Phase 4).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from app.classification.models import (
    ClassificationResult,
    ClassificationSignal,
    DocumentType,
    LaboratorySubtype,
)
from app.classification.normalize import MarkdownNormalizer, NormalizedDocument
from app.classification.scoring import (
    CLASSIFIER_VERSION,
    WEIGHT_STRONG,
    RuleScoringEngine,
    signal_score,
)
from app.classification.signals.appointment import AppointmentSignalDetector
from app.classification.signals.base import SignalDetector
from app.classification.signals.generic import GenericSignalDetector
from app.classification.signals.laboratory import LaboratorySignalDetector
from app.classification.signals.prescription import PrescriptionSignalDetector

if TYPE_CHECKING:
    from app.pipeline.context import ProcessingContext


class ClassificationService(Protocol):
    """Protocol for any service that classifies a normalized document."""

    async def classify(
        self,
        document: NormalizedDocument,
        context: ProcessingContext,
    ) -> ClassificationResult:
        """Classify ``document`` within ``context`` and return the result."""
        ...


class ClassificationServiceBase(ClassificationService):
    """Base marker for classification service implementations.

    Instantiation of the bare base raises ``NotImplementedError``; concrete
    implementations must override ``__init__``.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "ClassificationService implementations arrive after the M1 contract."
        )


# Recognized account-api ``client_type`` values and the type they boost (+5).
_CLIENT_HINT_MAP: dict[str, DocumentType] = {
    "lab_result": DocumentType.LABORATORY,
    "prescription": DocumentType.PRESCRIPTION,
}

_DEFAULT_DETECTORS: tuple[SignalDetector, ...] = (
    LaboratorySignalDetector(),
    AppointmentSignalDetector(),
    PrescriptionSignalDetector(),
    GenericSignalDetector(),
)


class RuleBasedClassificationService(ClassificationServiceBase):
    """Deterministic rule-based classifier (M2 Phase 3).

    Chain: detectors → (client hint) → ``RuleScoringEngine`` → result.
    The normalized document is produced upstream (pipeline Phase 4) and passed
    in; the normalizer is retained as a dependency for symmetry with the
    planning docs but is not invoked here.
    """

    def __init__(
        self,
        *,
        normalizer: MarkdownNormalizer | None = None,
        detectors: Sequence[SignalDetector] | None = None,
        engine: RuleScoringEngine | None = None,
    ) -> None:
        self._normalizer = normalizer or MarkdownNormalizer()
        self._detectors: Sequence[SignalDetector] = (
            list(detectors) if detectors is not None else _DEFAULT_DETECTORS
        )
        self._engine = engine or RuleScoringEngine()

    async def classify(
        self,
        document: NormalizedDocument,
        context: ProcessingContext,
    ) -> ClassificationResult:
        signals = [
            signal
            for detector in self._detectors
            for signal in detector.detect(document)
        ]
        hint_type = self._client_hint(context)
        if hint_type is not None:
            signals.append(
                ClassificationSignal(
                    name=f"{hint_type.value}.client_hint",
                    weight=WEIGHT_STRONG,
                    matched=True,
                    matches=1,
                )
            )

        document_type, confidence, reasons, decision, level = self._engine.score(
            signals
        )
        scored = self._engine.scored_signals(signals)

        subtype: str | None = None
        if document_type is DocumentType.LABORATORY:
            subtype = self._laboratory_subtype(scored)

        return ClassificationResult(
            document_type=document_type,
            document_subtype=subtype,
            confidence=confidence,
            confidence_level=level,
            decision=decision,
            method="rule_score",
            reasons=reasons,
            signals=scored,
            classifier_version=CLASSIFIER_VERSION,
            warnings=self._warnings(decision, level),
        )

    @staticmethod
    def _client_hint(context: ProcessingContext) -> DocumentType | None:
        value = (context.client_type or "").strip().lower()
        return _CLIENT_HINT_MAP.get(value)

    @staticmethod
    def _laboratory_subtype(signals: Sequence[ClassificationSignal]) -> str | None:
        """Laboratory subtype: hematology >= biomarker and > 0 else biomarker."""
        def score_of(name: str) -> float:
            return sum(signal_score(s) for s in signals if s.name == name)

        hematology = score_of("laboratory.hematology_marker")
        biomarker = score_of("laboratory.biomarker")
        if hematology > 0 and hematology >= biomarker:
            return LaboratorySubtype.HEMATOLOGY.value
        if biomarker > 0 and biomarker > hematology:
            return LaboratorySubtype.BIOCHEMISTRY.value
        return None

    @staticmethod
    def _warnings(decision: object, level: object) -> list[str]:
        warnings: list[str] = []
        if getattr(level, "value", level) == "low":
            warnings.append("low confidence")
        if getattr(decision, "value", decision) == "ambiguous":
            warnings.append("ambiguous classification")
        return warnings


__all__ = ["ClassificationService", "ClassificationServiceBase", "RuleBasedClassificationService"]