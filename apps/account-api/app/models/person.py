from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, Enum, Float, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.medical import Sex
from app.models.utils import utcnow


class Person(Base):
    """A physical person as a subject of medical data (DB_MODELS.md #5)."""

    __tablename__ = "persons"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), default="")
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    sex: Mapped[Sex | None] = mapped_column(
        Enum(Sex, native_enum=False, length=16), nullable=True
    )
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profession: Mapped[str | None] = mapped_column(String(255), nullable=True)
    height: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
