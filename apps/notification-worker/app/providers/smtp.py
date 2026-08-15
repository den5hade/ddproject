import asyncio
import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings
from app.providers.base import NotificationProvider


class SmtpProvider:
    """Delivers OTP codes by email over SMTP (run in a thread, non-blocking)."""

    async def send(self, *, to: str, channel: str, code: str) -> None:
        if channel != "email":
            raise ValueError(f"SMTpProvider cannot deliver to channel={channel!r}")
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = to
        message["Subject"] = "Your verification code"
        message.set_content(f"Your DDProject verification code is: {code}")

        await asyncio.to_thread(self._deliver, settings.smtp_host, settings.smtp_port, message)

    def _deliver(self, host: str, port: int, message: EmailMessage) -> None:
        context = ssl.create_default_context() if settings.smtp_use_tls else None
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            if context is not None:
                smtp.starttls(context=context)
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)


def build_provider() -> NotificationProvider:
    if not settings.smtp_host:
        raise RuntimeError("notification_provider=smtp requires SMTP_HOST to be set")
    return SmtpProvider()