import asyncio
import logging

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


async def run_consumer() -> None:
    """Blocking consumer loop; exits quietly when the broker is unreachable."""
    consumer = Consumer(
        dsn=settings.rabbitmq_dsn,
        queue_name=settings.document_events_queue,
        routing_keys=settings.document_events_routing_key_list,
    )
    try:
        await consumer.start()
    except Exception:
        logger.warning("document_consumer_start_failed", exc_info=True)
        return
    logger.info("document_consumer_started queue=%s", settings.document_events_queue)
    try:
        async for message in consumer.messages():
            await _handle(message)
    except asyncio.CancelledError:
        raise
    finally:
        await consumer.close()


__all__ = ["run_consumer"]