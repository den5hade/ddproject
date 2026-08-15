from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.medical import EncounterStatus, EncounterType
from app.models.utils import utcnow


class Encounter(Base):
    """A specific medical encounter / visit with a specialist (DB_MODELS.md #16)."""

    __tablename__ = "encounters"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    medical_record_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("medical_records.id", ondelete="CASCADE"), index=True
    )
    specialist_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("specialists.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type: Mapped[EncounterType] = mapped_column(
        Enum(EncounterType, native_enum=False, length=32), default=EncounterType.CONSULTATION
    )
    status: Mapped[EncounterStatus] = mapped_column(
        Enum(EncounterStatus, native_enum=False, length=16), default=EncounterStatus.SCHEDULED
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )