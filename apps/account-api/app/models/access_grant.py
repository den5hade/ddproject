from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.access import GrantStatus
from app.models.utils import utcnow


class PatientAccessGrant(Base):
    """Fine-grained grant: how a specialist account may access a patient (#24)."""

    __tablename__ = "patient_access_grants"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    patient_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        index=True,
        comment="specialist account",
    )
    organization_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    can_view_documents: Mapped[bool] = mapped_column(Boolean, default=False)
    can_upload_documents: Mapped[bool] = mapped_column(Boolean, default=False)
    can_view_extractions: Mapped[bool] = mapped_column(Boolean, default=False)
    can_view_analytics: Mapped[bool] = mapped_column(Boolean, default=False)
    can_create_encounters: Mapped[bool] = mapped_column(Boolean, default=False)
    can_edit_medical_data: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[GrantStatus] = mapped_column(
        Enum(GrantStatus, native_enum=False, length=16), default=GrantStatus.ACTIVE
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    granted_by_account_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    access_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )