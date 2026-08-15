from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.domain.account import AccountStatus
from app.models.utils import utcnow

if TYPE_CHECKING:
    from app.models.person import Person


class Account(Base):
    """Technical login account (DB_MODELS.md #3)."""

    __tablename__ = "accounts"

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, comment="account internal id"
    )
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_normalized: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, comment="lowercase email"
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone_e164: Mapped[str | None] = mapped_column(
        String(32), unique=True, nullable=True, comment="phone in E.164"
    )
    phone_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus, native_enum=False, length=32), default=AccountStatus.PENDING
    )
    person_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("persons.id", ondelete="SET NULL"),
        unique=True,
        nullable=True,
        comment="1:1 link to the physical person",
    )
    is_subscribed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    person: Mapped[Person | None] = relationship(lazy="joined")

    def __repr__(self) -> str:
        return f"<Account id={self.id} status={self.status.value}>"