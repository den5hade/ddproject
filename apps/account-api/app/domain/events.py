from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class DomainEvent:
    entity_id: UUID
    user_type: str
    session_id: UUID
    occurred_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class SessionCreatedEvent(DomainEvent):
    """A new authentication session was established."""


@dataclass(frozen=True)
class SessionRevokedEvent(DomainEvent):
    """An authentication session was revoked (logout / rotation)."""


__all__ = ["DomainEvent", "SessionCreatedEvent", "SessionRevokedEvent"]