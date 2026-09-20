import logging

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from aio_pika.abc import (
    AbstractChannel,
    AbstractExchange,
    AbstractRobustConnection,
)
from pydantic import BaseModel

logger = logging.getLogger("messaging.publisher")

EVENTS_EXCHANGE = "pdf.events"
CONTENT_TYPE_JSON = "application/json"


class Publisher:
    """Publishes Pydantic events to the topic exchange.

    Publishes are **mandatory** (routed or returned); returned messages are
    logged as warnings, never raised, so upload flow keeps working on partially
    started stacks.
    """

    def __init__(
        self,
        exchange: AbstractExchange,
        connection: AbstractRobustConnection,
        channel: AbstractChannel,
    ) -> None:
        self._exchange = exchange
        self._connection = connection
        self._channel = channel

    async def publish(self, routing_key: str, event: BaseModel) -> None:
        published = await self._exchange.publish(
            Message(
                body=event.model_dump_json().encode(),
                content_type=CONTENT_TYPE_JSON,
                type=event.__class__.__name__,
                delivery_mode=DeliveryMode.PERSISTENT,
            ),
            routing_key=routing_key,
            mandatory=True,
        )
        if not published:
            logger.warning(
                "unroutable_message routing_key=%s type=%s",
                routing_key,
                event.__class__.__name__,
            )

    async def close(self) -> None:
        await self._connection.close()


async def connect_publisher(dsn: str, exchange_name: str = EVENTS_EXCHANGE) -> Publisher:
    connection = await aio_pika.connect_robust(dsn)
    channel = await connection.channel(publisher_confirms=True)
    exchange = await channel.declare_exchange(exchange_name, ExchangeType.TOPIC, durable=True)
    return Publisher(exchange, connection, channel)
