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
from app.domain.access import AuditAction
from app.domain.account import AccountStatus
from app.domain.auth_session import AuthSession
from app.domain.user_type import UserType
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.auth_sessions import AuthSessionRepository
from app.schemas.auth import TokenResponse
from app.services.audit import AuditService
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
        self._accounts = AccountRepository(session)
        self._sessions = AuthSessionRepository(session)
        self._otp_service = otp_service
        self._notifier = notifier
        self._audit = AuditService(session)

    async def request_otp(self, identity: str) -> None:
        if not await self._otp_service.can_request(identity):
            raise RateLimitError("too many OTP requests, retry later")
        account, _created = await self._accounts.get_or_create_by_identity(identity)
        code = await self._otp_service.issue(identity)
        expires_at = datetime.now(UTC) + timedelta(seconds=OTP_TTL_SECONDS)
        await self._notifier.send_otp(
            identity, detect_channel(identity), code, expires_at
        )
        await self._session.commit()
        logger.info("otp_requested account_id=%s identity=%s", account.id, identity)

    async def verify_otp(self, identity: str, code: str, client: ClientInfo) -> TokenResponse:
        if not await self._otp_service.verify(identity, code):
            raise OtpVerificationError("invalid or expired OTP code")
        account = await self._accounts.get_by_identity(identity)
        if account is None:
            raise OtpVerificationError("no account for identity")
        if account.status != AccountStatus.ACTIVE:
            account.status = AccountStatus.ACTIVE
        return await self._establish_session(account, client)

    async def refresh(self, refresh_token: str, client: ClientInfo) -> TokenResponse:
        hmac = hash_refresh_token(refresh_token)
        current = await self._sessions.get_by_refresh_hmac(hmac)
        if current is None or not current.is_valid():
            raise RefreshTokenError("refresh token is unknown, expired, or revoked")

        current.revoke()
        await self._sessions.save(current)
        self._dispatch_events(current)

        account = await self._accounts.get_by_id(current.account_id)
        if account is None:
            raise RefreshTokenError("session account no longer exists")
        return await self._establish_session(
            account,
            client,
            reuse=current,
        )

    async def logout(self, refresh_token: str, client: ClientInfo | None = None) -> None:
        hmac = hash_refresh_token(refresh_token)
        current = await self._sessions.get_by_refresh_hmac(hmac)
        if current is None:
            raise RefreshTokenError("refresh token is unknown")
        current.revoke()
        await self._sessions.save(current)
        self._dispatch_events(current)
        await self._audit.record(
            action=AuditAction.LOGOUT,
            resource_type="account",
            resource_id=current.account_id,
            actor_account_id=current.account_id,
            ip_address=client.ip_address if client else "",
            user_agent=client.user_agent if client else "",
            metadata={"session_id": str(current.id)},
            commit=False,
        )
        await self._session.commit()

    async def _establish_session(
        self, account: Account, client: ClientInfo, reuse: AuthSession | None = None
    ) -> TokenResponse:
        refresh_token = generate_refresh_token()
        auth_session = AuthSession.create(
            account_id=account.id,
            user_type=UserType.USER,
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
        await self._audit.record(
            action=AuditAction.LOGIN,
            resource_type="account",
            resource_id=account.id,
            actor_account_id=account.id,
            ip_address=client.ip_address,
            user_agent=client.user_agent,
            metadata={"session_id": str(auth_session.id)},
            commit=False,
        )
        await self._session.commit()

        access_token = create_access_token(account.id, auth_session.user_type, auth_session.id)
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    @staticmethod
    def _dispatch_events(auth_session: AuthSession) -> None:
        for event in auth_session.pop_events():
            logger.info(
                "session_event event=%s session_id=%s",
                type(event).__name__,
                event.session_id,
            )