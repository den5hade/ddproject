from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field


def _occurred_at() -> datetime:
    return datetime.now(UTC)


class NotificationRequested(BaseModel):
    """Published by account-api on ``notification.requested`` when a notification
    must be delivered to an account (``notification-worker`` handles it).

    The payload carries only delivery and reference data — recipient address,
    a rendered subject/body, and the target resource ids. It never carries
    medical data (no diagnosis, values, filenames, or canonical JSON).
    """

    event_id: UUID
    occurred_at: datetime = Field(default_factory=_occurred_at)
    event_version: int = 1
    notification_id: UUID
    account_id: UUID
    organization_id: UUID | None = None
    type: str
    channel: str
    to: str
    subject: str
    body: str
    resource_type: str = "document"
    resource_id: UUID