import logging

from app.providers.base import NotificationProvider

logger = logging.getLogger("notification_worker.console")


class ConsoleProvider:
    """Delivers notifications to the application log (dev/test fallback)."""

    async def send(self, *, to: str, channel: str, code: str) -> None:
        logger.info("otp_delivery to=%s channel=%s code=%s", to, channel, code)

    async def send_message(self, *, to: str, channel: str, subject: str, body: str) -> None:
        logger.info(
            "notification_delivery to=%s channel=%s subject=%s", to, channel, subject
        )


def build_provider() -> NotificationProvider:
    return ConsoleProvider()