from collections.abc import AsyncIterator

import aio_pika
from aio_pika import ExchangeType
from aio_pika.abc import AbstractIncomingMessage, AbstractRobustChannel, AbstractRobustConnection

from messaging.publisher import EVENTS_EXCHANGE


class Consumer:
    """Consumes Pydantic events from a durable queue bound to the topic exchange.

    The queue is declared with a dead-letter exchange so messages rejected
    without requeue land in ``<queue>_dlq`` instead of disappearing.
    """

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
        self._dlx_name = f"{queue_name}_dlx"
        self._dlq_name = f"{queue_name}_dlq"
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractRobustChannel | None = None
        self._queue = None

    async def start(self) -> None:
        try:
            self._connection = await aio_pika.connect_robust(self._dsn)
            self._channel = await self._connection.channel()
            await self._channel.set_qos(prefetch_count=self._prefetch_count)
            exchange = await self._channel.declare_exchange(
                self._exchange_name, ExchangeType.TOPIC, durable=True
            )
            dlx = await self._channel.declare_exchange(
                self._dlx_name, ExchangeType.FANOUT, durable=True
            )
            dlq = await self._channel.declare_queue(self._dlq_name, durable=True)
            await dlq.bind(dlx)
            self._queue = await self._channel.declare_queue(
                self._queue_name,
                durable=True,
                arguments={"x-dead-letter-exchange": self._dlx_name},
            )
            for routing_key in self._routing_keys:
                await self._queue.bind(exchange, routing_key=routing_key)
        except Exception:
            await self.close()
            raise

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
        self._channel = None
        self._queue = None
