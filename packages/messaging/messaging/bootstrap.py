import asyncio
import logging
import os

from messaging.consumer import Consumer
from messaging.topology import CONSUMER_QUEUES

logger = logging.getLogger("messaging.bootstrap")


async def bootstrap(dsn: str) -> None:
    """Declare every consumer queue + its DLX/DLQ and bindings.

    Reuses :class:`Consumer.start()` so the declaration matches what the live
    workers declare byte-for-byte (durable queues, same arguments). One-shot:
    exits after declaring; the queues/bindings persist on the broker.
    """
    for spec in CONSUMER_QUEUES:
        consumer = Consumer(
            dsn=dsn,
            queue_name=spec.queue,
            routing_keys=spec.routing_keys,
        )
        await consumer.start()
        await consumer.close()
        logger.info("topology_declared queue=%s", spec.queue)


def _dsn_from_env() -> str:
    url = os.environ.get("RABBITMQ_URL")
    if url:
        return url
    host = os.environ.get("RABBITMQ_HOST", "localhost")
    port = os.environ.get("RABBITMQ_PORT", "5672")
    user = os.environ.get("RABBITMQ_USER", "")
    password = os.environ.get("RABBITMQ_PASSWORD", "")
    vhost = os.environ.get("RABBITMQ_VHOST", "/").lstrip("/")
    return f"amqp://{user}:{password}@{host}:{port}/{vhost}"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger.info("topology_bootstrap_started")
    asyncio.run(bootstrap(_dsn_from_env()))


if __name__ == "__main__":
    main()