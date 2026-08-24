import logging
from datetime import UTC, datetime, timedelta

import pytest
from app.repositories.account import AccountRepository
from app.services.auth import AuthService
from app.services.notifications import (
    NotificationUnavailableError,
    RabbitNotificationGateway,
)
from app.services.otp import OtpService


def _expires() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=300)


class ExplodingPublisher:
    async def publish(self, routing_key: str, event) -> None:
        raise RuntimeError("broker connection lost")


async def test_missing_publisher_fails_closed():
    gateway = RabbitNotificationGateway(None)
    with pytest.raises(NotificationUnavailableError):
        await gateway.send_otp(
            "user@example.com", "email", "123456", _expires()
        )


async def test_publish_failure_wrapped_as_unavailable():
    gateway = RabbitNotificationGateway(ExplodingPublisher())
    with pytest.raises(NotificationUnavailableError):
        await gateway.send_otp(
            "user@example.com", "email", "123456", _expires()
        )


async def test_no_otp_code_ever_reaches_logs(caplog):
    gateway = RabbitNotificationGateway(None)
    with caplog.at_level(logging.DEBUG), pytest.raises(NotificationUnavailableError):
        await gateway.send_otp(
            "user@example.com", "email", "654321", _expires()
        )
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "654321" not in joined


class CapturingGateway:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_otp(self, identity: str, channel: str, code, expires_at) -> None:
        self.sent.append((identity, code))


async def test_failed_delivery_deletes_pending_code(db_session, fake_redis):
    identity = "cleanup@example.com"
    otp_service = OtpService(fake_redis)
    accounts = AccountRepository(db_session)
    await accounts.get_or_create_by_identity(identity)
    await db_session.commit()

    service = AuthService(
        db_session,
        otp_service=otp_service,
        notifier=RabbitNotificationGateway(None),
    )
    with pytest.raises(NotificationUnavailableError):
        await service.request_otp(identity)

    assert await fake_redis.get(f"otp:code:{identity}") is None
    assert await fake_redis.get(f"otp:attempts:{identity}") is None
