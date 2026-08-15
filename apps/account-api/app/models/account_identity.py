from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.domain.account import IdentityKind
from app.models.utils import utcnow

if TYPE_CHECKING:
    from app.models.account import Account


class AccountIdentity(Base):
    """Normalized identity (email / phone) belonging to an account."""

    __tablename__ = "account_identities"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[IdentityKind] = mapped_column(
        Enum(IdentityKind, native_enum=False, length=16)
    )
    value: Mapped[str] = mapped_column(String(255), comment="value as supplied")
    value_normalized: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, comment="unique normalized form"
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    account: Mapped[Account] = relationship(lazy="joined")