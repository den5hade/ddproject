import logging
import re
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from contracts.events import AuthOtpRequested
from messaging import Publisher

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

OTP_ROUTING_KEY = "auth.otp.requested"

logger = logging.getLogger("account_api.notifications")


def detect_channel(identity: str) -> str:
    return "email" if EMAIL_RE.match(identity) else "phone"


class NotificationGateway(Protocol):
    async def send_otp(
        self, identity: str, channel: str, code: str, expires_at: datetime
    ) -> None: ...


class RabbitNotificationGateway:
    """Publishes OTP events to the events exchange; logs when the broker is down."""

    def __init__(self, publisher: Publisher | None) -> None:
        self._publisher = publisher

    async def send_otp(self, identity: str, channel: str, code: str, expires_at: datetime) -> None:
        if self._publisher is None:
            logger.info("otp_delivered_via_log", identity=identity, channel=channel, code=code)
            return
        event = AuthOtpRequested(
            request_id=uuid4(),
            identity=identity,
            channel=channel,
            code=code,
            expires_at=expires_at,
        )
        await self._publisher.publish(OTP_ROUTING_KEY, event)