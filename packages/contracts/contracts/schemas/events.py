from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field


def _occurred_at() -> datetime:
    return datetime.now(UTC)


class DocumentEvent(BaseModel):
    """Base payload shared by all document pipeline events (EVENTS.md)."""

    event_id: UUID
    schema_version: int = 1
    document_id: UUID
    document_version_id: UUID | None = None
    patient_id: UUID
    occurred_at: datetime = Field(default_factory=_occurred_at)