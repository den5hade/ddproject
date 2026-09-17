import asyncio
import logging
from typing import Literal
from uuid import uuid4

from aio_pika.abc import AbstractIncomingMessage
from contracts.events import AuthOtpRequested, NotificationDelivered, NotificationRequested
from messaging import Consumer, Publisher, connect_publisher
from pydantic import ValidationError

from app.config import settings
from app.providers import get_provider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("notification_worker")

DELIVERY_ROUTING_KEY = "notification.delivered"


async def handle(message: AbstractIncomingMessage, publisher: Publisher | None) -> None:
    async with message.process():
        if message.type == "AuthOtpRequested":
            await _handle_otp(message)
        elif message.type == "NotificationRequested":
            await _handle_notification(message, publisher)
        else:
            logger.warning("invalid_event dropped type=%s", message.type)


async def _handle_otp(message: AbstractIncomingMessage) -> None:
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


async def _handle_notification(
    message: AbstractIncomingMessage, publisher: Publisher | None
) -> None:
    try:
        event = NotificationRequested.model_validate_json(message.body)
    except ValidationError as exc:
        logger.warning("invalid_notification_event dropped error=%s", exc)
        return
    provider = get_provider()
    try:
        await provider.send_message(
            to=event.to,
            channel=event.channel,
            subject=event.subject,
            body=event.body,
        )
    except Exception as exc:
        logger.warning(
            "notification_failed notification_id=%s error=%s",
            event.notification_id,
            exc,
        )
        await _publish_delivery(
            publisher, event.notification_id, status="failed", error=str(exc)
        )
        return
    logger.info(
        "notification_delivered notification_id=%s to=%s subject=%s",
        event.notification_id,
        event.to,
        event.subject,
    )
    await _publish_delivery(publisher, event.notification_id, status="sent")


async def _publish_delivery(
    publisher: Publisher | None,
    notification_id,
    *,
    status: Literal["sent", "failed"],
    error: str | None = None,
) -> None:
    if publisher is None:
        logger.warning(
            "notification_result_dropped notification_id=%s status=%s", notification_id, status
        )
        return
    event = NotificationDelivered(
        event_id=uuid4(),
        notification_id=notification_id,
        status=status,
        error_message=error,
    )
    try:
        await publisher.publish(DELIVERY_ROUTING_KEY, event)
    except Exception:
        logger.warning(
            "notification_result_publish_failed notification_id=%s status=%s",
            notification_id,
            status,
            exc_info=True,
        )


async def run() -> None:
    consumer = Consumer(
        dsn=settings.broker_url,
        queue_name=settings.notification_queue,
        routing_keys=settings.routing_keys,
    )
    publisher = await connect_publisher(settings.broker_url)
    await consumer.start()
    logger.info(
        "notification_worker_started queue=%s routing_keys=%s",
        settings.notification_queue,
        settings.routing_keys,
    )
    try:
        async for message in consumer.messages():
            await handle(message, publisher)
    finally:
        await publisher.close()
        await consumer.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("notification_worker_stopped")


if __name__ == "__main__":
    main()