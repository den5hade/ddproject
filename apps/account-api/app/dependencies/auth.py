from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.bus import get_publisher
from app.core.database import get_db
from app.core.security import ExpiredTokenError, InvalidTokenError, decode_access_token
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.services.auth import AuthService, ClientInfo
from app.services.notifications import RabbitNotificationGateway
from app.services.otp import OtpService

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_account(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> Account:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_access_token(credentials.credentials)
    except ExpiredTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    account = await AccountRepository(session).get_by_id(UUID(claims["sub"]))
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="account not found"
        )
    return account


async def get_otp_service() -> OtpService:
    return OtpService()


async def get_auth_service(
    session: AsyncSession = Depends(get_db),
    otp_service: OtpService = Depends(get_otp_service),
) -> AuthService:
    publisher = await get_publisher()
    return AuthService(
        session=session,
        otp_service=otp_service,
        notifier=RabbitNotificationGateway(publisher),
    )


def client_info(
    request,
    *,
    device_id: str | None = None,
    platform: str | None = None,
    app_version: str | None = None,
) -> ClientInfo:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        ip_address = forwarded_for.split(",")[0].strip()
    else:
        ip_address = request.client.host if request.client else ""
    return ClientInfo(
        user_agent=request.headers.get("user-agent", ""),
        ip_address=ip_address,
        device_id=device_id,
        platform=platform,
        app_version=app_version,
    )


CurrentAccount = Annotated[Account, Depends(get_current_account)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
OtpServiceDep = Annotated[OtpService, Depends(get_otp_service)]