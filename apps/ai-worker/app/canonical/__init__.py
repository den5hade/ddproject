"""Canonical document processing: extraction, validation, and rendering glue.

The shared schema *models* (``BuildCanonicalResult``, ``LaboratoryCanonical``,
and friends) live in ``canonical`` (``packages/canonical``); this package holds
the ai-worker's concrete strategies and metadata composition around them.
"""

from app.canonical.extraction import ExtractionStrategy
from app.canonical.rendering import (
    PIPELINE_VERSION,
    SCHEMA_VERSION,
    build_frontmatter_meta,
    build_source_meta,
)
from app.canonical.validation import build_validation_meta

__all__ = [
    "ExtractionStrategy",
    "PIPELINE_VERSION",
    "SCHEMA_VERSION",
    "build_frontmatter_meta",
    "build_source_meta",
    "build_validation_meta",
]