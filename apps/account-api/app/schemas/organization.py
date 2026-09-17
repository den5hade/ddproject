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
from app.domain.account import IdentityKind
from app.domain.identity import Identity
from app.domain.medical import (
    DocumentType,
    MembershipStatus,
    OrganizationStatus,
    OrganizationType,
)
from app.domain.organization import (
    BranchStatus,
    OrganizationApiKeyScope,
    OrganizationApiKeyStatus,
    OrganizationDocumentSchemaStatus,
    OrganizationLicenseStatus,
    OrganizationMembershipRole,
    OrganizationVerificationStatus,
    inn_checksum_valid,
    normalize_inn,
    normalize_ogrn,
    ogrn_checksum_valid,
)


def normalize_inn_digits(v: object) -> str | None:
    """Shared INN normalizer: canonical digits + checksum (behind config flag)."""
    if v is None or v == "":
        return None
    value = normalize_inn(str(v))
    if not value.isdigit() or len(value) not in (10, 12):
        raise ValueError("INN must be 10 or 12 digits")
    if settings.integration_validate_inn_checksum and not inn_checksum_valid(value):
        raise ValueError("INN fails the control-digit check")
    return value


def normalize_ogrn_digits(v: object) -> str | None:
    """Shared OGRN normalizer: canonical digits + checksum."""
    if v is None or v == "":
        return None
    value = normalize_ogrn(str(v))
    if not value.isdigit() or len(value) != 13:
        raise ValueError("OGRN must be 13 digits")
    if not ogrn_checksum_valid(value):
        raise ValueError("OGRN fails the control-digit check")
    return value


def normalize_member_email(v: object) -> str:
    """Shared representative-email normalizer: identity-validated, lowercase."""
    if v is None or v == "":
        raise ValueError("administrator email is required")
    parsed = Identity.parse(str(v))
    if parsed.kind is not IdentityKind.EMAIL:
        raise ValueError("administrator identity must be an email address")
    return parsed.canonical


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: OrganizationType
    inn: str = Field(max_length=12)
    ogrn: str = Field(max_length=13)
    legal_address: str | None = Field(default=None, max_length=2000)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    website: str | None = Field(default=None, max_length=255)

    @field_validator("inn", mode="before")
    @classmethod
    def _normalize_inn(cls, v: object) -> str | None:
        return normalize_inn_digits(v)

    @field_validator("ogrn", mode="before")
    @classmethod
    def _normalize_ogrn(cls, v: object) -> str | None:
        return normalize_ogrn_digits(v)


class OrganizationMemberCreate(BaseModel):
    email: str
    role: OrganizationMembershipRole = OrganizationMembershipRole.OWNER

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, v: object) -> str:
        return normalize_member_email(v)


class OrganizationAdminCreate(BaseModel):
    organization: OrganizationCreate
    administrator: OrganizationMemberCreate


class OrganizationMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: UUID
    account_id: UUID
    role: OrganizationMembershipRole
    status: MembershipStatus
    joined_at: datetime

    @field_serializer("joined_at")
    def _tz(self, v: datetime) -> datetime:
        return to_api_tz(v)


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
        return normalize_inn_digits(v)

    @field_validator("ogrn", mode="before")
    @classmethod
    def _normalize_ogrn(cls, v: object) -> str | None:
        return normalize_ogrn_digits(v)

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


def validate_schema_definition(v: object) -> dict:
    """Structural validation for an org JSON-Schema definition.

    A metadata-registry guard, not a full JSON-Schema validator: the payload
    must be a JSON object and, where present, its ``type``/``properties``
    shapes must be well-formed. This keeps the org schema a registry entry
    (never coupled to the platform canonical model); full conformance is
    deferred with LLM consumption.
    """
    if not isinstance(v, dict):
        raise ValueError("schema_definition must be a JSON object")
    if "type" in v and not isinstance(v["type"], str):
        raise ValueError("schema_definition.type must be a string")
    properties = v.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            raise ValueError("schema_definition.properties must be an object")
        for key, sub in properties.items():
            if not isinstance(key, str) or not isinstance(sub, dict):
                raise ValueError(
                    "schema_definition.properties entries must be objects keyed by "
                    "field name"
                )
    return v


class OrganizationDocumentSchemaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    document_type: DocumentType = DocumentType.OTHER
    schema_definition: dict

    @field_validator("schema_definition", mode="before")
    @classmethod
    def _validate_definition(cls, v: object) -> dict:
        return validate_schema_definition(v)

    @field_validator("description", mode="before")
    @classmethod
    def _blank_to_none(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        return str(v)


class OrganizationDocumentSchemaUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    document_type: DocumentType | None = None
    schema_definition: dict | None = None

    @field_validator("schema_definition", mode="before")
    @classmethod
    def _validate_definition(cls, v: object) -> dict | None:
        if v is None:
            return None
        return validate_schema_definition(v)

    @field_validator("description", mode="before")
    @classmethod
    def _blank_to_none(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        return str(v)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "OrganizationDocumentSchemaUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("at least one field must be set")
        return self


class OrganizationDocumentSchemaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    document_type: DocumentType
    schema_definition: dict
    version: int
    status: OrganizationDocumentSchemaStatus
    created_by_account_id: UUID | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("published_at", "created_at", "updated_at")
    def _tz(self, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        return to_api_tz(v)


class OrganizationApiUsageDay(BaseModel):
    """Per-day aggregates for an organization (Phase 4h monitoring).

    Counts and rates only — this response intentionally carries **no PII**
    (no patient emails, request paths, IPs or user agents) so it is safe to
    serve to the organization's management users.
    """

    date: date
    requests: int
    successes: int
    errors: int
    success_rate: float
    error_rate: float
    documents: int
    documents_failed: int
    batches: int
    batch_items_failed: int


class OrganizationApiUsageResponse(BaseModel):
    """Aggregated API usage over an inclusive ``from``/``to`` day range.

    ``days`` is a sparse per-day series (only days with at least one recorded
    event); ``total_*``/``avg_*`` roll the series up. ``from``/``to`` are the
    JSON keys (``from`` is a Python keyword, hence the field names below).

    .. note:: day boundaries are UTC (v1 semantics).
    """

    model_config = ConfigDict()

    from_date: date = Field(serialization_alias="from")
    to_date: date = Field(serialization_alias="to")
    organization_id: UUID
    days: list[OrganizationApiUsageDay]
    total_requests: int
    total_successes: int
    total_errors: int
    overall_success_rate: float
    overall_error_rate: float
    total_documents: int
    total_documents_failed: int
    total_batches: int
    total_batch_items_failed: int