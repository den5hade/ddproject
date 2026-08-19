from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.dependencies.auth import AuthServiceDep, CurrentAccount, client_info
from app.models.account import Account
from app.schemas.auth import (
    RefreshRequest,
    RequestOtpRequest,
    TokenResponse,
    UserResponse,
    VerifyOtpRequest,
)
from app.services.auth import (
    OtpVerificationError,
    RateLimitError,
    RefreshTokenError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/request-otp", status_code=status.HTTP_202_ACCEPTED, response_model=None)
async def request_otp(
    payload: RequestOtpRequest,
    service: AuthServiceDep,
) -> dict | JSONResponse:
    try:
        await service.request_otp(payload.identity)
    except RateLimitError as exc:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": str(exc)},
        )
    return {"detail": "OTP sent"}


@router.post("/verify", response_model=TokenResponse)
async def verify_otp(
    payload: VerifyOtpRequest,
    request: Request,
    service: AuthServiceDep,
) -> TokenResponse | JSONResponse:
    client = client_info(
        request,
        device_id=payload.device_id,
        platform=payload.platform,
        app_version=payload.app_version,
    )
    try:
        return await service.verify_otp(payload.identity, payload.code, client)
    except OtpVerificationError as exc:
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    service: AuthServiceDep,
) -> TokenResponse | JSONResponse:
    client = client_info(
        request,
        device_id=payload.device_id,
        platform=payload.platform,
        app_version=payload.app_version,
    )
    try:
        return await service.refresh(payload.refresh_token, client)
    except RefreshTokenError as exc:
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": str(exc)})


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def logout(
    payload: RefreshRequest,
    request: Request,
    service: AuthServiceDep,
) -> None | JSONResponse:
    client = client_info(request)
    try:
        await service.logout(payload.refresh_token, client)
    except RefreshTokenError as exc:
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": str(exc)})
    return None


@router.get("/me", response_model=UserResponse)
async def me(account: CurrentAccount) -> Account:
    return account