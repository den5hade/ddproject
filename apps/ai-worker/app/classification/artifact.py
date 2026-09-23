"""Classification artifact serialization.

Builds the versioned ``classification_result.json`` S3 artifact — the
Python-determined verdict plus extraction provenance (model, prompt version,
schema version) and processing metadata. Written only after the canonical
payload passes schema validation.
"""

import json
from datetime import UTC, datetime
from typing import Any

from app.classification.models import ClassificationResult

__all__ = ["build_classification_artifact"]


def build_classification_artifact(
    *,
    classification: ClassificationResult,
    prompt_key: str,
    schema_name: str,
    prompt_version: str,
    model: str,
    processing: dict[str, Any],
) -> str:
    """Serialize the classification 2.0 verdict into the artifact payload.

    Args:
        classification: The rule-based classification result.
        prompt_key: Canonical extraction prompt key actually used.
        schema_name: Canonical schema validated for this document.
        prompt_version: Prompt template version of the extraction prompt.
        model: LLM model used for extraction.
        processing: Processing metadata (context ids + timestamps).

    Returns:
        Compact, stable JSON encoding of verdict + provenance.
    """
    payload: dict[str, Any] = classification.model_dump(mode="json")
    payload["signals"] = [signal.model_dump(mode="json") for signal in classification.signals]
    payload["processing"] = {
        "prompt_key": prompt_key,
        "schema_name": schema_name,
        "prompt_version": prompt_version,
        "model": model,
        **processing,
    }
    payload["generated_at"] = datetime.now(UTC).isoformat()
    return json.dumps(payload, ensure_ascii=False, indent=2)