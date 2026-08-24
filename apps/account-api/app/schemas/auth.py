from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.account import AccountStatus
from app.domain.identity import Identity


def _canonical_identity(value: str) -> str:
    return Identity.parse(value).canonical


class RequestOtpRequest(BaseModel):
    identity: str = Field(
        min_length=3, max_length=255, description="email address or phone number"
    )

    _normalize_identity = field_validator("identity")(_canonical_identity)


class VerifyOtpRequest(BaseModel):
    identity: str = Field(min_length=3, max_length=255)
    code: str = Field(pattern=r"^\d{6}$", description="6-digit one-time code")
    device_id: str | None = None
    platform: str | None = None
    app_version: str | None = None

    _normalize_identity = field_validator("identity")(_canonical_identity)


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
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str | None
    phone: str | None
    status: AccountStatus
    is_subscribed: bool