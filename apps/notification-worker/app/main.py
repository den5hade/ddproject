import asyncio
import logging

from aio_pika.abc import AbstractIncomingMessage
from contracts.events import AuthOtpRequested
from messaging import Consumer
from pydantic import ValidationError

from app.config import settings
from app.providers import get_provider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("notification_worker")


async def handle(message: AbstractIncomingMessage) -> None:
    async with message.process():
        try:
            event = AuthOtpRequested.model_validate_json(message.body)
        except ValidationError as exc:
            logger.warning("invalid_otp_event dropped error=%s", exc)
            return
        provider = get_provider()
        await provider.send(to=event.identity, channel=event.channel, code=event.code)
        logger.info(
            "otp_delivered identity=%s channel=%s request_id=%s",
            event.identity,
            event.channel,
            event.request_id,
        )


async def run() -> None:
    consumer = Consumer(
        dsn=settings.broker_url,
        queue_name=settings.notification_queue,
        routing_keys=settings.routing_keys,
    )
    await consumer.start()
    logger.info(
        "notification_worker_started queue=%s routing_keys=%s",
        settings.notification_queue,
        settings.routing_keys,
    )
    try:
        async for message in consumer.messages():
            await handle(message)
    finally:
        await consumer.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("notification_worker_stopped")


if __name__ == "__main__":
    main()