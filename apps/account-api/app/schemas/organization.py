from datetime import date, datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.core.config import settings
from app.core.timezone import to_api_tz
from app.domain.medical import OrganizationStatus, OrganizationType
from app.domain.organization import (
    BranchStatus,
    OrganizationApiKeyScope,
    OrganizationApiKeyStatus,
    OrganizationLicenseStatus,
    OrganizationVerificationStatus,
    inn_checksum_valid,
    normalize_inn,
    normalize_ogrn,
    ogrn_checksum_valid,
)


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    inn: str | None = Field(default=None, max_length=12)
    ogrn: str | None = Field(default=None, max_length=13)
    legal_address: str | None = Field(default=None, max_length=2000)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    website: str | None = Field(default=None, max_length=255)

    @field_validator("inn", mode="before")
    @classmethod
    def _normalize_inn(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        value = normalize_inn(str(v))
        if not value.isdigit() or len(value) not in (10, 12):
            raise ValueError("INN must be 10 or 12 digits")
        if settings.integration_validate_inn_checksum and not inn_checksum_valid(value):
            raise ValueError("INN fails the control-digit check")
        return value

    @field_validator("ogrn", mode="before")
    @classmethod
    def _normalize_ogrn(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        value = normalize_ogrn(str(v))
        if not value.isdigit() or len(value) != 13:
            raise ValueError("OGRN must be 13 digits")
        if not ogrn_checksum_valid(value):
            raise ValueError("OGRN fails the control-digit check")
        return value

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "OrganizationUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("at least one field must be set")
        return self


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    type: OrganizationType
    status: OrganizationStatus
    inn: str | None
    ogrn: str | None
    legal_address: str | None
    email: str | None
    phone: str | None
    website: str | None
    verification_status: OrganizationVerificationStatus
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _tz(self, v: datetime) -> datetime:
        return to_api_tz(v)


_BRANCH_CODE_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"


class BranchCreate(BaseModel):
    code: str = Field(pattern=_BRANCH_CODE_PATTERN)
    name: str = Field(min_length=1, max_length=255)
    address: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)

    @field_validator("address", "phone", mode="before")
    @classmethod
    def _blank_to_none(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        return str(v)


class BranchUpdate(BaseModel):
    code: str | None = Field(default=None, pattern=_BRANCH_CODE_PATTERN)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    address: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)

    @field_validator("address", "phone", mode="before")
    @classmethod
    def _blank_to_none(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        return str(v)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "BranchUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("at least one field must be set")
        return self


class BranchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    code: str
    name: str
    address: str | None
    phone: str | None
    status: BranchStatus
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _tz(self, v: datetime) -> datetime:
        return to_api_tz(v)


class LicenseCreate(BaseModel):
    license_number: str = Field(min_length=1, max_length=64)
    license_type: str = Field(min_length=1, max_length=64)
    status: OrganizationLicenseStatus = OrganizationLicenseStatus.ACTIVE
    issued_at: date | None = None
    expires_at: date | None = None
    scope: str | None = Field(default=None, max_length=255)
    issuer: str | None = Field(default=None, max_length=255)

    @field_validator("scope", "issuer", mode="before")
    @classmethod
    def _blank_to_none(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        return str(v)

    @model_validator(mode="after")
    def _dates_ordered(self) -> "LicenseCreate":
        if (
            self.issued_at is not None
            and self.expires_at is not None
            and self.expires_at < self.issued_at
        ):
            raise ValueError("expires_at must not be before issued_at")
        return self


class LicenseUpdate(BaseModel):
    license_number: str | None = Field(default=None, min_length=1, max_length=64)
    license_type: str | None = Field(default=None, min_length=1, max_length=64)
    status: OrganizationLicenseStatus | None = None
    issued_at: date | None = None
    expires_at: date | None = None
    scope: str | None = Field(default=None, max_length=255)
    issuer: str | None = Field(default=None, max_length=255)

    @field_validator("scope", "issuer", mode="before")
    @classmethod
    def _blank_to_none(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        return str(v)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "LicenseUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("at least one field must be set")
        return self

    @model_validator(mode="after")
    def _dates_ordered(self) -> "LicenseUpdate":
        if (
            self.issued_at is not None
            and self.expires_at is not None
            and self.expires_at < self.issued_at
        ):
            raise ValueError("expires_at must not be before issued_at")
        return self


class LicenseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    license_number: str
    license_type: str
    status: OrganizationLicenseStatus
    issued_at: date | None
    expires_at: date | None
    scope: str | None
    issuer: str | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _tz(self, v: datetime) -> datetime:
        return to_api_tz(v)


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    scopes: list[OrganizationApiKeyScope] = Field(min_length=1)
    expires_at: datetime | None = None


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    prefix: str
    status: OrganizationApiKeyStatus
    permissions: list[str] | None
    created_by_account_id: UUID | None
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None

    @field_serializer("created_at", "expires_at", "revoked_at", "last_used_at")
    def _tz(self, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        return to_api_tz(v)


class ApiKeyCreateResponse(ApiKeyResponse):
    """Returned once on create/rotate — includes the raw key."""
    raw_key: str