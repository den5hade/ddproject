import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
)
from app.domain.auth_session import AuthSession
from app.models.user import User
from app.repositories.auth_sessions import AuthSessionRepository
from app.repositories.users import UserRepository
from app.schemas.auth import TokenResponse
from app.services.notifications import NotificationGateway, detect_channel
from app.services.otp import OTP_TTL_SECONDS, OtpService

logger = logging.getLogger("account_api.auth")


class AuthError(Exception):
    """Base class for authentication failures."""


class RateLimitError(AuthError):
    """User asked for an OTP too often."""


class OtpVerificationError(AuthError):
    """The provided OTP is missing, wrong, or was burned by too many attempts."""


class RefreshTokenError(AuthError):
    """The refresh token is unknown, expired, or revoked."""


@dataclass
class ClientInfo:
    user_agent: str
    ip_address: str
    device_id: str | None = None
    platform: str | None = None
    app_version: str | None = None


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        otp_service: OtpService,
        notifier: NotificationGateway,
    ) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._sessions = AuthSessionRepository(session)
        self._otp_service = otp_service
        self._notifier = notifier

    async def request_otp(self, identity: str) -> None:
        if not await self._otp_service.can_request(identity):
            raise RateLimitError("too many OTP requests, retry later")
        user, _created = await self._users.get_or_create_by_identity(identity)
        code = await self._otp_service.issue(identity)
        expires_at = datetime.now(UTC) + timedelta(seconds=OTP_TTL_SECONDS)
        await self._notifier.send_otp(
            identity, detect_channel(identity), code, expires_at
        )
        await self._session.commit()
        logger.info("otp_requested", user_id=str(user.id), identity=identity)

    async def verify_otp(self, identity: str, code: str, client: ClientInfo) -> TokenResponse:
        if not await self._otp_service.verify(identity, code):
            raise OtpVerificationError("invalid or expired OTP code")
        user = await self._users.get_by_identity(identity)
        if user is None:
            raise OtpVerificationError("no user for identity")
        return await self._establish_session(user, client)

    async def refresh(self, refresh_token: str, client: ClientInfo) -> TokenResponse:
        hmac = hash_refresh_token(refresh_token)
        current = await self._sessions.get_by_refresh_hmac(hmac)
        if current is None or not current.is_valid():
            raise RefreshTokenError("refresh token is unknown, expired, or revoked")

        current.revoke()
        await self._sessions.save(current)
        self._dispatch_events(current, "revoked")

        user = await self._users.get_by_id(current.user_id)
        if user is None:
            raise RefreshTokenError("session user no longer exists")
        return await self._establish_session(
            user,
            client,
            reuse=current,
        )

    async def logout(self, refresh_token: str) -> None:
        hmac = hash_refresh_token(refresh_token)
        current = await self._sessions.get_by_refresh_hmac(hmac)
        if current is None:
            raise RefreshTokenError("refresh token is unknown")
        current.revoke()
        await self._sessions.save(current)
        self._dispatch_events(current)
        await self._session.commit()

    async def _establish_session(
        self, user: User, client: ClientInfo, reuse: AuthSession | None = None
    ) -> TokenResponse:
        refresh_token = generate_refresh_token()
        auth_session = AuthSession.create(
            user_id=user.id,
            user_type=user.user_type,
            refresh_token_hmac=hash_refresh_token(refresh_token),
            user_agent=client.user_agent,
            ip_address=client.ip_address,
            device_id=client.device_id,
            platform=client.platform,
            app_version=client.app_version,
            expires_at=datetime.now(UTC)
            + timedelta(days=settings.jwt_refresh_expire_days),
        )
        if reuse is not None:
            auth_session.device_id = reuse.device_id or client.device_id
            auth_session.platform = reuse.platform or client.platform
            auth_session.app_version = reuse.app_version or client.app_version

        await self._sessions.save(auth_session)
        self._dispatch_events(auth_session)
        await self._session.commit()

        access_token = create_access_token(user.id, user.user_type, auth_session.id)
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    @staticmethod
    def _dispatch_events(auth_session: AuthSession) -> None:
        for event in auth_session.pop_events():
            logger.info(
                "session_event",
                event=type(event).__name__,
                session_id=str(event.session_id),
            )