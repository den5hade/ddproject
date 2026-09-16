from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field


def _occurred_at() -> datetime:
    return datetime.now(UTC)


class OrganizationBatchCreated(BaseModel):
    """Published by account-api on ``organization.batch.created`` when a bulk
    upload batch is accepted (Phase 4e).

    The batch header is committed before any item is processed; this event is
    the asynchronous notification that processing has started. Per-item
    correlation (``external_id``) is deferred to ``OrganizationBatchCompleted``
    / the per-item document events.
    """

    event_id: UUID
    occurred_at: datetime = Field(default_factory=_occurred_at)
    event_version: int = 1
    organization_id: UUID
    batch_id: UUID
    total_count: int