from collections.abc import AsyncIterator

import aio_pika
from aio_pika import ExchangeType
from aio_pika.abc import AbstractIncomingMessage, AbstractRobustChannel, AbstractRobustConnection

from messaging.publisher import EVENTS_EXCHANGE


class Consumer:
    """Consumes Pydantic events from a durable queue bound to the topic exchange."""

    def __init__(
        self,
        dsn: str,
        queue_name: str,
        routing_keys: list[str],
        exchange_name: str = EVENTS_EXCHANGE,
        prefetch_count: int = 10,
    ) -> None:
        self._dsn = dsn
        self._queue_name = queue_name
        self._routing_keys = routing_keys
        self._exchange_name = exchange_name
        self._prefetch_count = prefetch_count
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractRobustChannel | None = None
        self._queue = None

    async def start(self) -> None:
        self._connection = await aio_pika.connect_robust(self._dsn)
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=self._prefetch_count)
        exchange = await self._channel.declare_exchange(
            self._exchange_name, ExchangeType.TOPIC, durable=True
        )
        self._queue = await self._channel.declare_queue(self._queue_name, durable=True)
        for routing_key in self._routing_keys:
            await self._queue.bind(exchange, routing_key=routing_key)

    async def messages(self) -> AsyncIterator[AbstractIncomingMessage]:
        if self._queue is None:
            await self.start()
        async with self._queue.iterator() as messages:
            async for message in messages:
                yield message

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None