"""Heuristic document classification (offline, no LLM calls).

Public API surface for the Classification 2.0 contract (Phase 1: domain
types). ``classify_document_type`` is the legacy keyword classifier and
remains available for the current pipeline.
"""

from app.classification.classifier import classify_document_type
from app.classification.exceptions import (
    ClassificationError,
    InvalidClassificationInputError,
    SchemaResolutionError,
)
from app.classification.models import (
    ClassificationConfidenceLevel,
    ClassificationDecision,
    ClassificationMethod,
    ClassificationResult,
    ClassificationSignal,
    DocumentType,
    LaboratorySubtype,
)
from app.classification.normalize import NormalizedDocument
from app.classification.scoring import CLASSIFIER_VERSION

__all__ = [
    "CLASSIFIER_VERSION",
    "ClassificationConfidenceLevel",
    "ClassificationDecision",
    "ClassificationError",
    "ClassificationMethod",
    "ClassificationResult",
    "ClassificationSignal",
    "DocumentType",
    "InvalidClassificationInputError",
    "LaboratorySubtype",
    "NormalizedDocument",
    "SchemaResolutionError",
    "classify_document_type",
]
