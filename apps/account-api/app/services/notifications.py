import logging
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from contracts.events import AuthOtpRequested, NotificationRequested
from messaging import Publisher
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.identity import Identity
from app.domain.organization import (
    NotificationStatus,
    NotificationType,
)
from app.models.notification import Notification

OTP_ROUTING_KEY = "auth.otp.requested"
NOTIFICATION_ROUTING_KEY = "notification.requested"

logger = logging.getLogger("account_api.notifications")


def detect_channel(identity: str) -> str:
    return Identity.parse(identity).kind.value


class NotificationUnavailableError(Exception):
    """The OTP could not be handed to the delivery broker."""


class NotificationGateway(Protocol):
    async def send_otp(
        self, identity: str, channel: str, code: str, expires_at: datetime
    ) -> None: ...


class RabbitNotificationGateway:
    """Publishes OTP events to the events exchange; fails closed."""

    def __init__(self, publisher: Publisher | None) -> None:
        self._publisher = publisher

    async def send_otp(self, identity: str, channel: str, code: str, expires_at: datetime) -> None:
        if self._publisher is None:
            raise NotificationUnavailableError("notification delivery is unavailable")
        event = AuthOtpRequested(
            request_id=uuid4(),
            identity=identity,
            channel=channel,
            code=code,
            expires_at=expires_at,
        )
        try:
            await self._publisher.publish(OTP_ROUTING_KEY, event)
        except Exception as exc:
            raise NotificationUnavailableError(
                "notification delivery failed"
            ) from exc


def notification_subject(notification_type: NotificationType, org_name: str) -> str:
    """Rendered subject line — carries only org name, never medical data."""
    if notification_type is NotificationType.DOCUMENT_PROCESSING_FAILED:
        return f"Document processing failed — {org_name}"
    if notification_type is NotificationType.DOCUMENT_RECEIVED:
        return f"Document received — {org_name}"
    return f"Document processed — {org_name}"


def notification_body(
    notification_type: NotificationType,
    org_name: str,
    secure_link: str,
    resource_id: UUID,
) -> str:
    """Rendered body — org name + secure link + document reference only.

    Deliberately no medical data: no diagnosis, values, filenames or canonical
    JSON (spec §4.12 / §7).
    """
    reference = f"Reference: {resource_id}"
    if notification_type is NotificationType.DOCUMENT_PROCESSING_FAILED:
        return (
            f"{org_name} sent you a medical document that could not be "
            f"processed. View details: {secure_link} ({reference})."
        )
    return (
        f"{org_name} processed your medical document. "
        f"View it: {secure_link} ({reference})."
    )


class NotificationService:
    """Persists notification rows and hands delivery to notification-worker.

    Delivery is a best-effort side channel: a publish failure never propagates
    to the caller (the document pipeline keeps working). ``status`` moves
    PENDING -> SENT/FAILED via ``NotificationDelivered`` handling, then READ.
    """

    def __init__(self, session: AsyncSession, publisher: Publisher | None) -> None:
        self._session = session
        self._publisher = publisher

    async def create_for_document(
        self,
        *,
        account_id: UUID,
        organization_id: UUID | None,
        notification_type: NotificationType,
        org_name: str,
        to_email: str,
        secure_link: str,
        resource_id: UUID,
    ) -> Notification:
        notification = Notification(
            account_id=account_id,
            organization_id=organization_id,
            type=notification_type,
            title=notification_subject(notification_type, org_name),
            template=notification_body(
                notification_type, org_name, secure_link, resource_id
            ),
            resource_id=resource_id,
        )
        self._session.add(notification)
        await self._session.flush()

        event = NotificationRequested(
            event_id=uuid4(),
            notification_id=notification.id,
            account_id=account_id,
            organization_id=organization_id,
            type=notification_type.value,
            channel=notification.channel.value,
            to=to_email,
            subject=notification.title,
            body=notification.template,
            resource_id=resource_id,
        )
        try:
            await self._publish(event)
        except Exception:
            notification.status = NotificationStatus.FAILED
            notification.error_message = "publish failed"
            logger.warning(
                "notification_publish_failed notification_id=%s", notification.id,
                exc_info=True,
            )
        await self._session.commit()
        return notification

    async def mark_delivered(self, notification_id: UUID) -> None:
        notification = await self._session.get(Notification, notification_id)
        if notification is None:
            return
        notification.status = NotificationStatus.SENT
        notification.sent_at = datetime.now(UTC)
        await self._session.commit()

    async def mark_failed(self, notification_id: UUID, error: str | None) -> None:
        notification = await self._session.get(Notification, notification_id)
        if notification is None:
            return
        notification.status = NotificationStatus.FAILED
        notification.error_message = (error or "delivery failed")[:512]
        await self._session.commit()

    async def _publish(self, event: NotificationRequested) -> None:
        if self._publisher is None:
            raise NotificationUnavailableError("notification delivery is unavailable")
        await self._publisher.publish(NOTIFICATION_ROUTING_KEY, event)