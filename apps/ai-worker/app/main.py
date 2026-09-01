import asyncio
import logging

from aio_pika.abc import AbstractIncomingMessage
from contracts.events import DocumentConverted, DocumentUploaded
from messaging import Consumer, connect_publisher
from pydantic import ValidationError
from storage import CloudS3, StorageConfig

from app.config import settings
from app.processor import DocumentProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ai_worker")


def _cloud_s3() -> CloudS3:
    return CloudS3(
        StorageConfig(
            s3_endpoint_url=settings.s3_endpoint_url,
            s3_key_id=settings.s3_key_id,
            s3_key_secret=settings.s3_key_secret,
            s3_bucket_name=settings.s3_bucket_name,
            s3_region=settings.s3_region,
            s3_tenant_id=settings.s3_tenant_id,
        )
    )


async def _handle(message: AbstractIncomingMessage, processor: DocumentProcessor) -> None:
    async with message.process():
        try:
            if message.type == "DocumentUploaded":
                event = DocumentUploaded.model_validate_json(message.body)
                await processor.handle_converting(event)
            elif message.type == "DocumentConverted":
                event = DocumentConverted.model_validate_json(message.body)
                await processor.handle_structuring(event)
            else:
                logger.warning("unsupported_event_type type=%s", message.type)
        except ValidationError as exc:
            logger.warning("invalid_event dropped error=%s", exc)


async def run() -> None:
    s3 = _cloud_s3()
    if settings.s3_bucket_name:
        await asyncio.to_thread(s3.ensure_bucket)
    publisher = await connect_publisher(settings.rabbitmq_dsn)
    processor = DocumentProcessor(s3, publisher, settings)
    consumer = Consumer(
        dsn=settings.rabbitmq_dsn,
        queue_name=settings.ai_worker_queue,
        routing_keys=settings.routing_key_list,
    )
    await consumer.start()
    logger.info(
        "ai_worker_started queue=%s routing_keys=%s",
        settings.ai_worker_queue,
        settings.routing_key_list,
    )
    try:
        async for message in consumer.messages():
            await _handle(message, processor)
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
