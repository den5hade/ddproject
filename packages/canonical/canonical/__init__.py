"""Canonical extraction schema registry, validation and deterministic rendering.

``pdf-canonical`` provides the single-source-of-truth schema for LLM-extracted
documents, Pydantic validation, and Python-side rendering of ``structured.md``
with YAML frontmatter. It is shared by the ai-worker (production) and the
account-api (presentation).
"""

from canonical.metadata import (
    DocumentMeta,
    ExtractionMeta,
    FrontmatterMeta,
    ProcessingMeta,
    SourceMeta,
    ValidationMeta,
)
from canonical.render import render_document, render_frontmatter, render_markdown
from canonical.schemas import (
    CANONICAL_MODELS,
    DEFAULT_CANONICAL_MODEL,
    BaseCanonical,
    GenericCanonical,
    LaboratoryCanonical,
    PrescriptionCanonical,
    build_canonical,
)

__all__ = [
    "BaseCanonical",
    "CANONICAL_MODELS",
    "DEFAULT_CANONICAL_MODEL",
    "DocumentMeta",
    "ExtractionMeta",
    "FrontmatterMeta",
    "GenericCanonical",
    "LaboratoryCanonical",
    "PrescriptionCanonical",
    "ProcessingMeta",
    "SourceMeta",
    "ValidationMeta",
    "build_canonical",
    "render_document",
    "render_frontmatter",
    "render_markdown",
]
