"""Heuristic document classification (offline, no LLM calls).

Public API surface for the Classification 2.0 contract (Phase 1: domain
types). ``classify_document_type`` is the legacy keyword classifier and
remains available for the current pipeline.
"""

from app.classification.artifact import build_classification_artifact
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
from app.classification.normalize import MarkdownNormalizer, NormalizedDocument
from app.classification.resolver import RegistrySchemaResolver, SchemaResolver
from app.classification.scoring import CLASSIFIER_VERSION, RuleScoringEngine
from app.classification.service import RuleBasedClassificationService

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
    "MarkdownNormalizer",
    "NormalizedDocument",
    "RegistrySchemaResolver",
    "RuleBasedClassificationService",
    "RuleScoringEngine",
    "SchemaResolutionError",
    "SchemaResolver",
    "build_classification_artifact",
    "classify_document_type",
]
