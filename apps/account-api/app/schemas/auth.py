from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.account import AccountStatus


class RequestOtpRequest(BaseModel):
    identity: str = Field(
        min_length=3, max_length=255, description="email address or phone number"
    )


class VerifyOtpRequest(BaseModel):
    identity: str = Field(min_length=3, max_length=255)
    code: str = Field(pattern=r"^\d{6}$", description="6-digit one-time code")
    device_id: str | None = None
    platform: str | None = None
    app_version: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str
    device_id: str | None = None
    platform: str | None = None
    app_version: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: UUID
    email: str | None
    phone: str | None
    status: AccountStatus
    is_subscribed: bool