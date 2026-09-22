"""Outbound AMQP publishing wrapper."""

import logging

from messaging import connect_publisher
from messaging.publisher import Publisher as AmqpPublisher

logger = logging.getLogger(__name__)


class MessagePublisher:
    """Owns a pdf-messaging ``Publisher`` and its connection lifecycle."""

    def __init__(self, publisher: AmqpPublisher) -> None:
        self._publisher = publisher

    @classmethod
    async def connect(cls, dsn: str) -> "MessagePublisher":
        return cls(await connect_publisher(dsn))

    async def publish(self, routing_key: str, event) -> None:
        """Publish ``event`` under ``routing_key``; ack events on success."""
        await self._publisher.publish(routing_key, event)
        logger.info(
            "published routing_key=%s document_id=%s event_id=%s",
            routing_key,
            getattr(event, "document_id", None),
            getattr(event, "event_id", None),
        )

    async def close(self) -> None:
        await self._publisher.close()