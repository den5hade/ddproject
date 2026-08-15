from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.auth_session import AuthSession
from app.models.auth_session import AuthSessionRow


def _as_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class AuthSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def to_row(self, auth_session: AuthSession) -> AuthSessionRow:
        return AuthSessionRow(
            id=auth_session.id,
            account_id=auth_session.account_id,
            user_type=auth_session.user_type,
            refresh_token_hmac=auth_session.refresh_token_hmac,
            user_agent=auth_session.user_agent,
            ip_address=auth_session.ip_address,
            device_id=auth_session.device_id,
            platform=auth_session.platform,
            app_version=auth_session.app_version,
            expires_at=auth_session.expires_at,
            revoked_at=auth_session.revoked_at,
            created_at=auth_session.created_at,
            last_used_at=auth_session.last_used_at,
        )

    @staticmethod
    def from_row(row: AuthSessionRow) -> AuthSession:
        return AuthSession(
            id=row.id,
            account_id=row.account_id,
            user_type=row.user_type,
            refresh_token_hmac=row.refresh_token_hmac,
            user_agent=row.user_agent,
            ip_address=row.ip_address,
            device_id=row.device_id,
            platform=row.platform,
            app_version=row.app_version,
            expires_at=_as_utc(row.expires_at),
            revoked_at=_as_utc(row.revoked_at),
            created_at=_as_utc(row.created_at),
            last_used_at=_as_utc(row.last_used_at),
        )

    async def save(self, auth_session: AuthSession) -> None:
        existing = await self._session.get(AuthSessionRow, auth_session.id)
        if existing is not None:
            existing.refresh_token_hmac = auth_session.refresh_token_hmac
            existing.revoked_at = auth_session.revoked_at
            existing.expires_at = auth_session.expires_at
            existing.last_used_at = auth_session.last_used_at
            existing.user_agent = auth_session.user_agent
            existing.ip_address = auth_session.ip_address
            existing.device_id = auth_session.device_id
            existing.platform = auth_session.platform
            existing.app_version = auth_session.app_version
        else:
            self._session.add(self.to_row(auth_session))
        await self._session.flush()

    async def get_by_refresh_hmac(self, refresh_token_hmac: str) -> AuthSession | None:
        result = await self._session.execute(
            select(AuthSessionRow).where(
                AuthSessionRow.refresh_token_hmac == refresh_token_hmac
            )
        )
        row = result.scalar_one_or_none()
        return self.from_row(row) if row is not None else None

    async def get_by_id(self, session_id: UUID) -> AuthSession | None:
        row = await self._session.get(AuthSessionRow, session_id)
        return self.from_row(row) if row is not None else None