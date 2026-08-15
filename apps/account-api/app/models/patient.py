from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.medical import PatientStatus
from app.models.utils import utcnow


class Patient(Base):
    """A person in the patient role (DB_MODELS.md #12)."""

    __tablename__ = "patients"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    person_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("persons.id", ondelete="CASCADE"), unique=True, index=True
    )
    medical_record_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[PatientStatus] = mapped_column(
        Enum(PatientStatus, native_enum=False, length=16), default=PatientStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )