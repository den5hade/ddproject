"""Canonical rendering: YAML frontmatter metadata envelopes and output render."""

import logging
from typing import Any
from uuid import UUID

from canonical import FrontmatterMeta

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
PIPELINE_VERSION = "1.0.0"


def build_source_meta(
    event,
    *,
    declared_type: str | None = None,
) -> dict[str, Any]:
    """Compose the Python-built ``source`` block of the canonical frontmatter.

    Provenance comes from the ``DocumentConverted`` event: the markdown object
    key plus original file metadata.
    """
    source = {
        "object_key": event.output_storage_key,
        "filename": getattr(event, "original_filename", None),
        "mime_type": getattr(event, "mime_type", None),
        "sha256": getattr(event, "sha256", None),
    }
    if declared_type:
        source["declared_type"] = declared_type
    return source


def build_frontmatter_meta(
    *,
    document_id: UUID,
    canonical,
    source: dict[str, Any],
    page_count: int | None = None,
    model: str,
    prompt_version: str,
    tokens: dict[str, Any],
    validation: dict[str, Any],
    classification: Any | None = None,
) -> FrontmatterMeta:
    """Compose the full YAML metadata envelope around a rendered canonical doc."""
    return FrontmatterMeta(
        doc_id=str(document_id),
        type=canonical.type,
        subtype=canonical.subtype,
        document={
            "language": canonical.language,
            "document_date": canonical.document_date,
            "page_count": page_count,
        },
        source=source,
        processing={
            "pipeline_version": PIPELINE_VERSION,
            "extraction": {
                "model": model,
                "prompt_version": prompt_version,
                "schema": canonical.schema_name,
                "schema_version": SCHEMA_VERSION,
                "tokens": tokens,
                "cost_usd": 0.0,
            },
        },
        validation=validation,
        classification=classification,
    )