import asyncio
import logging
import random

from aio_pika.abc import AbstractIncomingMessage
from contracts.events import NotificationDelivered
from messaging import Consumer
from pydantic import ValidationError

from app.core.config import settings
from app.core.database import async_session_factory
from app.services.notifications import NotificationService

logger = logging.getLogger("account_api.consumer")

_EVENT_MODELS = {
    "NotificationDelivered": NotificationDelivered,
}

_BACKOFF_INITIAL_SECONDS = 1.0
_BACKOFF_MAX_SECONDS = 30.0


async def _handle(message: AbstractIncomingMessage) -> None:
    async with message.process():
        model = _EVENT_MODELS.get(message.type)
        if model is None:
            logger.warning("event_unsupported dropped type=%s", message.type)
            return
        try:
            event = model.model_validate_json(message.body)
        except ValidationError as exc:
            logger.warning("event_invalid dropped type=%s error=%s", message.type, exc)
            return
        async with async_session_factory() as session:
            service = NotificationService(session, publisher=None)
            if event.status == "sent":
                await service.mark_delivered(event.notification_id)
            else:
                await service.mark_failed(event.notification_id, event.error_message)


def _default_consumer() -> Consumer:
    return Consumer(
        dsn=settings.rabbitmq_dsn,
        queue_name=settings.notification_result_queue,
        routing_keys=settings.notification_result_routing_key_list,
    )


async def run_consumer(
    consumer_factory=None,
    sleep=None,
) -> None:
    """Reconnecting consumer loop for notification delivery results.

    Mirrors the document-events consumer: fresh ``Consumer`` per attempt with
    exponential backoff and jitter; handler failures are rejected without
    requeue (dead-lettered) while the loop keeps consuming.
    """
    factory = consumer_factory or _default_consumer
    do_sleep = sleep or asyncio.sleep
    delay = _BACKOFF_INITIAL_SECONDS
    while True:
        consumer = factory()
        try:
            await consumer.start()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "notification_consumer_start_failed retry_in=%.1fs", delay, exc_info=True
            )
            await do_sleep(delay)
            delay = min(delay * 2 + random.uniform(0, 0.5), _BACKOFF_MAX_SECONDS)
            continue

        logger.info(
            "notification_consumer_started queue=%s",
            settings.notification_result_queue,
        )
        try:
            handled_any = False
            async for message in consumer.messages():
                handled_any = True
                try:
                    await _handle(message)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.error(
                        "notification_event_handler_failed type=%s message_id=%s "
                        "delivery_tag=%s (rejected to %s)",
                        message.type,
                        message.message_id,
                        message.delivery_tag,
                        f"{settings.notification_result_queue}_dlq",
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            if handled_any:
                delay = _BACKOFF_INITIAL_SECONDS
            logger.warning(
                "notification_consumer_disconnected retry_in=%.1fs", delay, exc_info=True
            )
            await do_sleep(delay)
            delay = min(delay * 2 + random.uniform(0, 0.5), _BACKOFF_MAX_SECONDS)
        finally:
            await consumer.close()


__all__ = ["run_consumer"]