import logging
from email.message import EmailMessage
from uuid import uuid4

import app.main as main_module
import pytest
from app.providers.console import ConsoleProvider
from app.providers.smtp import SmtpProvider
from contracts.events import AuthOtpRequested, NotificationDelivered, NotificationRequested


@pytest.fixture
def caplog_worker(caplog):
    with caplog.at_level(logging.INFO, logger="notification_worker.console"):
        yield caplog


async def test_console_provider_sends_without_error():
    provider = ConsoleProvider()
    await provider.send(to="user@example.com", channel="email", code="123456")


async def test_console_provider_send_message_logs(caplog_worker):
    provider = ConsoleProvider()
    await provider.send_message(
        to="user@example.com",
        channel="email",
        subject="Document processed — City Clinic",
        body="City Clinic processed your medical document.",
    )
    joined = "\n".join(r.getMessage() for r in caplog_worker.records)
    assert "notification_delivery" in joined
    assert "user@example.com" in joined


async def test_smtp_provider_send_message_builds_email(monkeypatch):
    captured: dict[str, EmailMessage] = {}

    def _fake_deliver(self, host, port, message) -> None:
        captured["message"] = message

    monkeypatch.setattr(SmtpProvider, "_deliver", _fake_deliver)
    provider = SmtpProvider()
    await provider.send_message(
        to="user@example.com",
        channel="email",
        subject="Document processed — City Clinic",
        body="City Clinic processed your medical document.",
    )
    assert "user@example.com" in captured["message"]["To"]
    assert captured["message"]["Subject"] == "Document processed — City Clinic"
    assert captured["message"].get_content().strip() == (
        "City Clinic processed your medical document."
    )


async def test_smtp_provider_rejects_non_email_channel(monkeypatch):
    monkeypatch.setattr(SmtpProvider, "_deliver", lambda *a, **k: None)
    provider = SmtpProvider()
    with pytest.raises(ValueError):
        await provider.send_message(
            to="+79000000000",
            channel="phone",
            subject="s",
            body="b",
        )


async def test_otp_send_reuses_send_message_build(monkeypatch):
    captured = []

    async def _fake_send_message(self, *, to, channel, subject, body) -> None:
        captured.append((to, channel, subject, body))

    monkeypatch.setattr(SmtpProvider, "send_message", _fake_send_message)
    provider = SmtpProvider()
    await provider.send(to="user@example.com", channel="email", code="654321")
    assert captured[0][0] == "user@example.com"
    assert "654321" in captured[0][3]


class _ProcessCM:
    def __init__(self, msg):
        self._msg = msg

    async def __aenter__(self):
        return self._msg

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            return False
        self._msg.acked = True
        return True


class FakeMessage:
    def __init__(self, type_: str, body: bytes):
        self.type = type_
        self.body = body
        self.acked = False

    def process(self):
        return _ProcessCM(self)


class FakePublisher:
    def __init__(self):
        self.published = []

    async def publish(self, routing_key: str, event) -> None:
        self.published.append((routing_key, event))


class CapturingProvider:
    def __init__(self):
        self.otps = []
        self.messages = []
        self.fail_next = False

    async def send(self, *, to, channel, code) -> None:
        self.otps.append((to, channel, code))

    async def send_message(self, *, to, channel, subject, body) -> None:
        if self.fail_next:
            raise RuntimeError("smtp connection refused")
        self.messages.append((to, channel, subject, body))


def _notification_message() -> FakeMessage:
    event = NotificationRequested(
        event_id=uuid4(),
        notification_id=uuid4(),
        account_id=uuid4(),
        type="document_processed",
        channel="email",
        to="anna@clinic.example",
        subject="Document processed — City Clinic",
        body="City Clinic processed your medical document.",
        resource_id=uuid4(),
    )
    return FakeMessage("NotificationRequested", event.model_dump_json().encode())


async def test_handle_otp_delivers(monkeypatch):
    provider = CapturingProvider()
    monkeypatch.setattr(main_module, "get_provider", lambda: provider)
    event = AuthOtpRequested(
        request_id=uuid4(),
        identity="user@example.com",
        channel="email",
        code="123456",
        expires_at="2026-09-18T00:00:00Z",
    )
    message = FakeMessage("AuthOtpRequested", event.model_dump_json().encode())

    await main_module.handle(message, None)

    assert provider.otps == [("user@example.com", "email", "123456")]
    assert message.acked is True


async def test_handle_notification_delivers_and_reports_sent(monkeypatch):
    provider = CapturingProvider()
    monkeypatch.setattr(main_module, "get_provider", lambda: provider)
    message = _notification_message()
    publisher = FakePublisher()

    await main_module.handle(message, publisher)

    assert provider.messages[0][0] == "anna@clinic.example"
    assert provider.messages[0][2] == "Document processed — City Clinic"
    routing_key, event = publisher.published[0]
    assert routing_key == "notification.delivered"
    assert isinstance(event, NotificationDelivered)
    assert event.status == "sent"
    assert event.error_message is None
    assert message.acked is True


async def test_handle_notification_failure_reports_failed(monkeypatch):
    provider = CapturingProvider()
    provider.fail_next = True
    monkeypatch.setattr(main_module, "get_provider", lambda: provider)
    message = _notification_message()
    publisher = FakePublisher()

    await main_module.handle(message, publisher)

    routing_key, event = publisher.published[0]
    assert routing_key == "notification.delivered"
    assert isinstance(event, NotificationDelivered)
    assert event.status == "failed"
    assert "smtp connection refused" in event.error_message
    assert message.acked is True


async def test_handle_unknown_event_is_dropped(monkeypatch):
    provider = CapturingProvider()
    monkeypatch.setattr(main_module, "get_provider", lambda: provider)
    message = FakeMessage("SomeOtherEvent", b"{}")

    await main_module.handle(message, None)

    assert provider.otps == []
    assert provider.messages == []
    assert message.acked is True


async def test_result_not_published_without_publisher(monkeypatch):
    provider = CapturingProvider()
    monkeypatch.setattr(main_module, "get_provider", lambda: provider)
    message = _notification_message()

    await main_module.handle(message, None)

    assert provider.messages[0][0] == "anna@clinic.example"
    assert message.acked is True