"""Heuristic document classification (offline, no LLM calls)."""

from app.classification.classifier import classify_document_type
from app.classification.exceptions import ClassificationError

__all__ = ["ClassificationError", "classify_document_type"]