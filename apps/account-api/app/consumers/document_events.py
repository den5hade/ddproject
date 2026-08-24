import asyncio
import logging
import random

from aio_pika.abc import AbstractIncomingMessage
from contracts.events import (
    DocumentAnalysisCompleted,
    DocumentConverted,
    DocumentProcessingFailed,
    DocumentStored,
)
from messaging import Consumer
from pydantic import ValidationError

from app.core.bus import get_publisher
from app.core.config import settings
from app.core.database import async_session_factory
from app.services.documents import DocumentService
from app.services.storage import StorageService

logger = logging.getLogger("account_api.consumer")

_EVENT_MODELS = {
    "DocumentStored": DocumentStored,
    "DocumentConverted": DocumentConverted,
    "DocumentAnalysisCompleted": DocumentAnalysisCompleted,
    "DocumentProcessingFailed": DocumentProcessingFailed,
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
            publisher = await get_publisher()
            service = DocumentService(
                session,
                publisher=publisher,
                storage=StorageService.from_settings(),
            )
            if isinstance(event, DocumentStored):
                await service.on_document_stored(event)
            elif isinstance(event, DocumentConverted):
                await service.on_document_converted(event)
            elif isinstance(event, DocumentAnalysisCompleted):
                await service.on_document_analysis_completed(event)
            elif isinstance(event, DocumentProcessingFailed):
                await service.on_document_processing_failed(event)


def _default_consumer() -> Consumer:
    return Consumer(
        dsn=settings.rabbitmq_dsn,
        queue_name=settings.document_events_queue,
        routing_keys=settings.document_events_routing_key_list,
    )


async def run_consumer(
    consumer_factory=None,
    sleep=None,
) -> None:
    """Reconnecting consumer loop.

    Survives broker outages (fresh ``Consumer`` per attempt, exponential
    backoff with jitter) and handler failures (the message was rejected
    without requeue by ``message.process()``, so the broker dead-letters it;
    the loop logs and keeps consuming). ``CancelledError`` always propagates.
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
                "document_consumer_start_failed retry_in=%.1fs", delay, exc_info=True
            )
            await do_sleep(delay)
            delay = min(delay * 2 + random.uniform(0, 0.5), _BACKOFF_MAX_SECONDS)
            continue

        logger.info("document_consumer_started queue=%s", settings.document_events_queue)
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
                        "document_event_handler_failed type=%s message_id=%s "
                        "delivery_tag=%s (rejected to %s)",
                        message.type,
                        message.message_id,
                        message.delivery_tag,
                        f"{settings.document_events_queue}_dlq",
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            if handled_any:
                delay = _BACKOFF_INITIAL_SECONDS
            logger.warning(
                "document_consumer_disconnected retry_in=%.1fs", delay, exc_info=True
            )
            await do_sleep(delay)
            delay = min(delay * 2 + random.uniform(0, 0.5), _BACKOFF_MAX_SECONDS)
        finally:
            await consumer.close()


__all__ = ["run_consumer"]