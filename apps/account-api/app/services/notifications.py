import logging
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from contracts.events import AuthOtpRequested
from messaging import Publisher

from app.domain.identity import Identity

OTP_ROUTING_KEY = "auth.otp.requested"

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