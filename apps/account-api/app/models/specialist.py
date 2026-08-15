from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.medical import SpecialistStatus
from app.models.utils import utcnow


class Specialist(Base):
    """A person in the specialist (doctor) role."""

    __tablename__ = "specialists"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    person_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("persons.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[SpecialistStatus] = mapped_column(
        Enum(SpecialistStatus, native_enum=False, length=16), default=SpecialistStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Specialty(Base):
    """Medical specialty reference table."""

    __tablename__ = "specialties"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))


class SpecialistSpecialty(Base):
    """Many-to-many: specialist <-> specialties."""

    __tablename__ = "specialist_specialties"
    __table_args__ = (
        UniqueConstraint(
            "specialist_id", "specialty_id", name="uq_specialist_specialties_specialist_specialty"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    specialist_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("specialists.id", ondelete="CASCADE"), index=True
    )
    specialty_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("specialties.id", ondelete="CASCADE"), index=True
    )