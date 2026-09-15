from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Date, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.medical import MembershipStatus, OrganizationStatus, OrganizationType
from app.domain.organization import (
    BranchStatus,
    OrganizationApiKeyStatus,
    OrganizationLicenseStatus,
    OrganizationMembershipRole,
    OrganizationVerificationStatus,
)
from app.models.utils import utcnow


class Organization(Base):
    """Healthcare organization (clinic/hospital/lab, DB_MODELS.md #9)."""

    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[OrganizationType] = mapped_column(
        Enum(OrganizationType, native_enum=False, length=32)
    )
    status: Mapped[OrganizationStatus] = mapped_column(
        Enum(OrganizationStatus, native_enum=False, length=16),
        default=OrganizationStatus.ACTIVE,
    )
    inn: Mapped[str | None] = mapped_column(String(12), unique=True, nullable=True)
    ogrn: Mapped[str | None] = mapped_column(String(13), unique=True, nullable=True)
    legal_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification_status: Mapped[OrganizationVerificationStatus] = mapped_column(
        Enum(OrganizationVerificationStatus, native_enum=False, length=16),
        default=OrganizationVerificationStatus.UNVERIFIED,
        nullable=False,
    )
    created_by_account_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class OrganizationMembership(Base):
    """Account <-> organization membership with a position."""

    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "account_id", name="uq_organization_memberships_org_account"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[OrganizationMembershipRole] = mapped_column(
        Enum(OrganizationMembershipRole, native_enum=False, length=16),
        default=OrganizationMembershipRole.MEMBER,
        server_default="MEMBER",
        nullable=False,
    )
    status: Mapped[MembershipStatus] = mapped_column(
        Enum(MembershipStatus, native_enum=False, length=16), default=MembershipStatus.ACTIVE
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrganizationBranch(Base):
    """A branch (filial) of an organization."""

    __tablename__ = "organization_branches"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "code", name="uq_organization_branches_org_code"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[BranchStatus] = mapped_column(
        Enum(BranchStatus, native_enum=False, length=16), default=BranchStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class OrganizationLicense(Base):
    """A license held by an organization (registry-ready, history preserved)."""

    __tablename__ = "organization_licenses"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "license_number",
            name="uq_organization_licenses_org_number",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    license_number: Mapped[str] = mapped_column(String(64))
    license_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[OrganizationLicenseStatus] = mapped_column(
        Enum(OrganizationLicenseStatus, native_enum=False, length=16),
        default=OrganizationLicenseStatus.ACTIVE,
        nullable=False,
    )
    issued_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    scope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class OrganizationApiKey(Base):
    """A machine-to-machine API key for an organization (raw shown once)."""

    __tablename__ = "organization_api_keys"
    __table_args__ = (
        UniqueConstraint("key_hash", name="uq_organization_api_keys_key_hash"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(128))
    permissions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[OrganizationApiKeyStatus] = mapped_column(
        Enum(OrganizationApiKeyStatus, native_enum=False, length=16),
        default=OrganizationApiKeyStatus.ACTIVE,
    )
    created_by_account_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )