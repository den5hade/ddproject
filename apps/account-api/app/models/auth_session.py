from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.domain.user_type import UserType
from app.models.account import Account
from app.models.utils import utcnow


class AuthSessionRow(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, comment="session id"
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    user_type: Mapped[UserType] = mapped_column(
        Enum(UserType, native_enum=False, length=32)
    )
    refresh_token_hmac: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, comment="HMAC-SHA256 hex of refresh token"
    )
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    ip_address: Mapped[str] = mapped_column(
        String(45), default="", comment="client IP (IPv6 max length)"
    )
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    account: Mapped[Account] = relationship(lazy="joined")