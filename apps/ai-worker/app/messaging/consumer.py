"""Inbound AMQP consumer (queue subscription + ack handling)."""

from messaging import Consumer as AmqpConsumer

from app.config.settings import Settings


class QueueConsumer:
    """Owns the pdf-messaging ``Consumer`` for this worker's queue."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._consumer = AmqpConsumer(
            dsn=settings.rabbitmq_dsn,
            queue_name=settings.ai_worker_queue,
            routing_keys=settings.routing_key_list,
        )

    async def start(self) -> None:
        await self._consumer.start()

    def messages(self):
        """Async iterator of inbound ``AbstractIncomingMessage`` objects."""
        return self._consumer.messages()

    async def close(self) -> None:
        await self._consumer.close()