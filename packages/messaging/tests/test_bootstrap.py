import asyncio

import messaging.bootstrap as bootstrap_module
import pytest
from messaging.topology import CONSUMER_QUEUES

_ENV_KEYS = (
    "RABBITMQ_URL",
    "RABBITMQ_HOST",
    "RABBITMQ_PORT",
    "RABBITMQ_USER",
    "RABBITMQ_PASSWORD",
    "RABBITMQ_VHOST",
)


class FakeConsumer:
    created: list["FakeConsumer"] = []

    def __init__(self, dsn, queue_name, routing_keys):
        self.dsn = dsn
        self.queue_name = queue_name
        self.routing_keys = routing_keys
        self.started = False
        self.closed = False
        FakeConsumer.created.append(self)

    async def start(self):
        self.started = True

    async def close(self):
        self.closed = True


@pytest.fixture
def fake_consumer(monkeypatch):
    FakeConsumer.created = []
    monkeypatch.setattr(bootstrap_module, "Consumer", FakeConsumer)
    return FakeConsumer


def test_bootstrap_declares_all_specs(fake_consumer):
    asyncio.run(bootstrap_module.bootstrap("amqp://test"))

    assert len(fake_consumer.created) == len(CONSUMER_QUEUES)
    for consumer in fake_consumer.created:
        assert consumer.started
        assert consumer.closed

    queues = [consumer.queue_name for consumer in fake_consumer.created]
    for spec in CONSUMER_QUEUES:
        assert spec.queue in queues


def test_bootstrap_passes_routing_keys(fake_consumer):
    asyncio.run(bootstrap_module.bootstrap("amqp://test"))

    for consumer, spec in zip(fake_consumer.created, CONSUMER_QUEUES, strict=False):
        assert consumer.dsn == "amqp://test"
        assert consumer.queue_name == spec.queue


def test_dsn_from_env_url(monkeypatch):
    monkeypatch.setenv("RABBITMQ_URL", "amqp://user:pass@host:5672/vhost")
    assert bootstrap_module._dsn_from_env() == "amqp://user:pass@host:5672/vhost"


def test_dsn_from_env_parts(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RABBITMQ_HOST", "broker.local")
    monkeypatch.setenv("RABBITMQ_PORT", "5673")
    monkeypatch.setenv("RABBITMQ_USER", "pdf")
    monkeypatch.setenv("RABBITMQ_PASSWORD", "secret")
    monkeypatch.setenv("RABBITMQ_VHOST", "/dev")
    assert bootstrap_module._dsn_from_env() == "amqp://pdf:secret@broker.local:5673/dev"


def test_dsn_from_env_defaults(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    assert bootstrap_module._dsn_from_env() == "amqp://:@localhost:5672/"