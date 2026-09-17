from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.domain.medical import (
    DocumentType,
    MembershipStatus,
    OrganizationStatus,
    OrganizationType,
)
from app.domain.organization import (
    BatchItemStatus,
    BatchStatus,
    BranchStatus,
    OrganizationApiKeyStatus,
    OrganizationDocumentSchemaStatus,
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
    organization: Mapped[Organization | None] = relationship(
        lazy="selectin",
        foreign_keys=[organization_id],
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


class OrganizationApiRequest(Base):
    """High-volume, non-PII HTTP access log for /integration requests (Ph4c).

    Never stores request bodies, files, canonical JSON, patient emails or any
    other medical data (spec §24). ``organization_id``/``api_key_id`` are NULL
    for requests that failed before authentication succeeded.
    """

    __tablename__ = "organization_api_requests"
    __table_args__ = (
        Index(
            "ix_organization_api_requests_org_created",
            "organization_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    api_key_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("organization_api_keys.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    request_id: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(255))
    status_code: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class OrganizationUploadBatch(Base):
    """A bulk document upload submitted by an organization (Phase 4e).

    The batch header is committed before any item is processed; each item is
    then handled in its own transaction, so partial failures never roll back
    the batch. ``idempotency_key`` de-duplicates client retries at the batch
    level: the partial unique index (``idempotency_key IS NOT NULL``) mirrors
    migration 0013, so multiple NULL-key batches per organization stay legal.
    """

    __tablename__ = "organization_upload_batches"
    __table_args__ = (
        Index(
            "uq_organization_upload_batches_org_idem",
            "organization_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    api_key_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("organization_api_keys.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[BatchStatus] = mapped_column(
        Enum(BatchStatus, native_enum=False, length=16),
        default=BatchStatus.ACCEPTED,
        server_default="ACCEPTED",
        nullable=False,
    )
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    items: Mapped[list["OrganizationUploadBatchItem"]] = relationship(
        back_populates="batch",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="OrganizationUploadBatchItem.item_index",
    )


class OrganizationUploadBatchItem(Base):
    """A single item of an ``OrganizationUploadBatch`` (Phase 4e).

    Holds the caller-provided metadata (patient_email, document_type,
    external_id, branch_code, title) and the per-item outcome: ``status``
    (PENDING -> ACCEPTED with ``document_id`` set, or REJECTED with
    ``error_code``/``error_message``). The model intentionally carries no
    file bytes -- the upload file is streamed straight into the existing
    document pipeline per item.
    """

    __tablename__ = "organization_upload_batch_items"
    __table_args__ = (
        UniqueConstraint(
            "batch_id", "item_index", name="uq_organization_upload_batch_items_batch_index"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organization_upload_batches.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    item_index: Mapped[int] = mapped_column(Integer)
    patient_email: Mapped[str] = mapped_column(String(255))
    document_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType, native_enum=False, length=32),
        default=DocumentType.OTHER,
        server_default="OTHER",
        nullable=False,
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    branch_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[BatchItemStatus] = mapped_column(
        Enum(BatchItemStatus, native_enum=False, length=16),
        default=BatchItemStatus.PENDING,
        server_default="PENDING",
        nullable=False,
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    batch: Mapped[OrganizationUploadBatch] = relationship(back_populates="items")


class OrganizationDocumentSchema(Base):
    """A versioned JSON-Schema draft/published definition for an organization.

    A metadata registry that describes the structure of an organization's own
    document submissions (Phase 4g). ``version`` is monotonic per
    ``(organization_id, name)``; a row moves ``DRAFT -> PUBLISHED`` on publish
    and is then immutable — re-editing happens through a new version.
    ``schema_definition`` is a plain JSON object (JSON-Schema-ish) and never
    replaces or couples to the platform canonical schema. ``document_type`` is
    the platform ``DocumentType`` enum.
    """

    __tablename__ = "organization_document_schemas"
    __table_args__ = (
        Index(
            "uq_organization_document_schemas_org_name_ver",
            "organization_id",
            "name",
            "version",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType, native_enum=False, length=32),
        default=DocumentType.OTHER,
        server_default="OTHER",
        nullable=False,
    )
    schema_definition: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[OrganizationDocumentSchemaStatus] = mapped_column(
        Enum(OrganizationDocumentSchemaStatus, native_enum=False, length=16),
        default=OrganizationDocumentSchemaStatus.DRAFT,
        server_default="DRAFT",
        nullable=False,
    )
    organization: Mapped[Organization | None] = relationship(
        lazy="selectin",
        foreign_keys=[organization_id],
    )
    created_by_account_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )