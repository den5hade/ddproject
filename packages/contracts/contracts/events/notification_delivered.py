from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


def _occurred_at() -> datetime:
    return datetime.now(UTC)


class NotificationDelivered(BaseModel):
    """Published by notification-worker on ``notification.delivered`` after a
    delivery attempt, so account-api can move the row to SENT or FAILED.

    ``status`` carries the outcome; ``error_message`` is present on failure.
    """

    event_id: UUID
    occurred_at: datetime = Field(default_factory=_occurred_at)
    event_version: int = 1
    notification_id: UUID
    status: Literal["sent", "failed"]
    error_message: str | None = None