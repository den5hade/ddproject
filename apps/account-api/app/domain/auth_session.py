from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.domain.events import DomainEvent, SessionRevokedEvent
from app.domain.user_type import UserType

REFRESH_TOKEN_TTL = timedelta(days=30)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class AuthSession:
    """AuthSession Aggregate Root.

    Manages user authentication sessions with refresh token rotation.
    """

    id: UUID
    user_id: UUID
    user_type: UserType
    refresh_token_hmac: str  # HMAC, NOT plain SHA-256
    user_agent: str
    ip_address: str
    device_id: str | None = None
    platform: str | None = None
    app_version: str | None = None
    expires_at: datetime = field(default_factory=lambda: _utcnow() + REFRESH_TOKEN_TTL)
    revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=_utcnow)
    last_used_at: datetime = field(default_factory=_utcnow)

    # Внутренний буфер событий
    _domain_events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(
        cls,
        user_id: UUID,
        user_type: UserType,
        refresh_token_hmac: str,
        user_agent: str,
        ip_address: str,
        device_id: str | None = None,
        platform: str | None = None,
        app_version: str | None = None,
        expires_at: datetime | None = None,
    ) -> "AuthSession":
        session = cls(
            id=uuid4(),
            user_id=user_id,
            user_type=user_type,
            refresh_token_hmac=refresh_token_hmac,
            user_agent=user_agent,
            ip_address=ip_address,
            device_id=device_id,
            platform=platform,
            app_version=app_version,
            expires_at=expires_at or _utcnow() + REFRESH_TOKEN_TTL,
        )
        session.last_used_at = _utcnow()
        return session

    def revoke(self) -> None:
        """Отозвать эту сессию."""
        self.revoked_at = _utcnow()
        self._domain_events.append(
            SessionRevokedEvent(
                entity_id=self.user_id,
                user_type=str(self.user_type.value),
                session_id=self.id,
            )
        )

    def touch(self) -> None:
        """Обновить время последнего использования сессии."""
        self.last_used_at = _utcnow()

    def is_valid(self) -> bool:
        """Проверить, что сессия не истекла и не отозвана."""
        now = _utcnow()
        return self.revoked_at is None and self.expires_at > now

    def pop_events(self) -> list[DomainEvent]:
        """Извлечь и очистить буфер доменных событий."""
        events, self._domain_events = self._domain_events, []
        return events


__all__ = ["AuthSession", "REFRESH_TOKEN_TTL"]