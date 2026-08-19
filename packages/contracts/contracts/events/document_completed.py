from typing import Literal
from uuid import UUID

from contracts.schemas.events import DocumentEvent


class DocumentAnalysisCompleted(DocumentEvent):
    """ai-worker → account-api: structured extraction finished for a version."""

    extraction_id: UUID
    schema_name: str
    schema_version: str = "1"
    status: Literal["succeeded", "failed"]
    confidence: float | None = None
    data: dict | None = None