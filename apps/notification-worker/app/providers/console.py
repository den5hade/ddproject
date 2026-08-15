import logging

from app.providers.base import NotificationProvider

logger = logging.getLogger("notification_worker.console")


class ConsoleProvider:
    """Delivers OTP codes to the application log (dev/test fallback)."""

    async def send(self, *, to: str, channel: str, code: str) -> None:
        logger.info("otp_delivery to=%s channel=%s code=%s", to, channel, code)


def build_provider() -> NotificationProvider:
    return ConsoleProvider()