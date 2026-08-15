import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from aio_pika.abc import AbstractExchange, AbstractRobustConnection
from pydantic import BaseModel

EVENTS_EXCHANGE = "pdf.events"
CONTENT_TYPE_JSON = "application/json"


class Publisher:
    """Publishes Pydantic events to the topic exchange."""

    def __init__(self, exchange: AbstractExchange, connection: AbstractRobustConnection) -> None:
        self._exchange = exchange
        self._connection = connection

    async def publish(self, routing_key: str, event: BaseModel) -> None:
        await self._exchange.publish(
            Message(
                body=event.model_dump_json().encode(),
                content_type=CONTENT_TYPE_JSON,
                type=event.__class__.__name__,
                delivery_mode=DeliveryMode.PERSISTENT,
            ),
            routing_key=routing_key,
        )

    async def close(self) -> None:
        await self._connection.close()


async def connect_publisher(
    dsn: str, exchange_name: str = EVENTS_EXCHANGE
) -> Publisher:
    """Declare the events topic exchange and return a ready Publisher."""
    connection = await aio_pika.connect_robust(dsn)
    channel = await connection.channel()
    exchange = await channel.declare_exchange(
        exchange_name, ExchangeType.TOPIC, durable=True
    )
    return Publisher(exchange, connection)