from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.access import AuditAction
from app.models.utils import utcnow


class AuditLog(Base):
    """Who did what on which resource (DB_MODELS.md #29)."""

    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    actor_account_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, native_enum=False, length=64)
    )
    resource_type: Mapped[str] = mapped_column(String(64), default="")
    resource_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    patient_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ip_address: Mapped[str] = mapped_column(String(45), default="")
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)