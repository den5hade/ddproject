import asyncio
import logging

from aio_pika.abc import AbstractIncomingMessage
from contracts.events import DocumentUploadRequested
from messaging import Consumer, connect_publisher
from pydantic import ValidationError
from storage import CloudS3, StorageConfig

from app.config import settings
from app.processor import StorageProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("objectstorage_worker")


def _cloud_s3() -> CloudS3:
    return CloudS3(
        StorageConfig(
            s3_endpoint_url=settings.s3_endpoint_url,
            s3_key_id=settings.s3_key_id,
            s3_key_secret=settings.s3_key_secret,
            s3_bucket_name=settings.s3_bucket_name,
            s3_region=settings.s3_region,
        )
    )


async def _handle(message: AbstractIncomingMessage, processor: StorageProcessor) -> None:
    async with message.process():
        try:
            event = DocumentUploadRequested.model_validate_json(message.body)
        except ValidationError as exc:
            logger.warning("invalid_event dropped error=%s", exc)
            return
        await processor.process(event)


async def run() -> None:
    s3 = _cloud_s3()
    if settings.s3_bucket_name:
        await asyncio.to_thread(s3.ensure_bucket)
    publisher = await connect_publisher(settings.rabbitmq_dsn)
    processor = StorageProcessor(s3, publisher)
    consumer = Consumer(
        dsn=settings.rabbitmq_dsn,
        queue_name=settings.objectstorage_queue,
        routing_keys=settings.routing_key_list,
    )
    await consumer.start()
    logger.info(
        "objectstorage_worker_started queue=%s routing_keys=%s",
        settings.objectstorage_queue,
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
        logger.info("objectstorage_worker_stopped")


if __name__ == "__main__":
    main()