"""ai-worker runner: consume convert/structuring events and process them."""

import asyncio
import logging

from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError

from app.artifacts.storage import build_cloud_s3
from app.config.logging import setup_logging
from app.config.settings import settings
from app.messaging import MessagePublisher, QueueConsumer, decode_message
from app.pipeline.errors import PipelineError
from app.pipeline.pipeline import DocumentPipeline
from app.worker.lifecycle import ensure_storage

logger = logging.getLogger("ai_worker")


async def _handle(message: AbstractIncomingMessage, pipeline: DocumentPipeline) -> None:
    async with message.process():
        try:
            event = decode_message(message)
            if event is None:
                logger.warning("unsupported_event_type type=%s", message.type)
                return
            if message.type == "DocumentUploaded":
                await pipeline.handle_converting(event)
            else:
                await pipeline.handle_structuring(event)
        except (ValidationError, PipelineError) as exc:
            logger.warning("invalid_event dropped error=%s", exc)


async def run() -> None:
    setup_logging()

    s3 = build_cloud_s3(settings)
    await ensure_storage(s3, settings)

    publisher = await MessagePublisher.connect(settings.rabbitmq_dsn)
    pipeline = DocumentPipeline(s3, publisher, settings)

    consumer = QueueConsumer(settings)
    await consumer.start()
    logger.info(
        "ai_worker_started queue=%s routing_keys=%s",
        settings.ai_worker_queue,
        settings.routing_key_list,
    )
    try:
        async for message in consumer.messages():
            await _handle(message, pipeline)
    finally:
        await consumer.close()
        await publisher.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("ai_worker_stopped")


if __name__ == "__main__":
    main()