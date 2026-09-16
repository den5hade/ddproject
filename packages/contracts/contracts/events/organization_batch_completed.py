from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field


def _occurred_at() -> datetime:
    return datetime.now(UTC)


class OrganizationBatchCompleted(BaseModel):
    """Published by account-api on ``organization.batch.completed`` when a bulk
    upload batch reaches a terminal state (COMPLETED / PARTIAL / FAILED).

    ``status`` carries the ``BatchStatus`` value; the counters let a consumer
    reconcile per-item outcomes without polling. No medical data is included.
    """

    event_id: UUID
    occurred_at: datetime = Field(default_factory=_occurred_at)
    event_version: int = 1
    organization_id: UUID
    batch_id: UUID
    status: str
    total_count: int
    accepted_count: int
    failed_count: int