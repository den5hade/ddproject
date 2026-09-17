from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.organization import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
from app.models.utils import utcnow


class Notification(Base):
    """A delivery record for an account notification (Phase 4f).

    Created when an organization-sourced document finishes processing (or
    fails); notification-worker delivers it and reports back so ``status``
    moves PENDING -> SENT/FAILED, then READ when the client opens it.

    Intentionally carries no medical data: only the recipient account, source
    organization, a rendered subject/body, and the target resource ids.
    ``organization_id`` is SET NULL so history survives an org deletion.
    """

    __tablename__ = "notifications"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, native_enum=False, length=32),
        nullable=False,
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, native_enum=False, length=16),
        default=NotificationChannel.EMAIL,
        server_default="EMAIL",
        nullable=False,
    )
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, native_enum=False, length=16),
        default=NotificationStatus.PENDING,
        server_default="PENDING",
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(
        String(32), default="document", server_default="document", nullable=False
    )
    resource_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )