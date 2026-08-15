import asyncio
import logging

from messaging import Publisher, connect_publisher

from app.core.config import settings

logger = logging.getLogger("account_api.bus")

_publisher: Publisher | None = None


async def get_publisher() -> Publisher | None:
    """Lazily connect once; returns None when the broker is unreachable."""
    global _publisher
    if _publisher is not None:
        return _publisher
    try:
        _publisher = await asyncio.wait_for(
            connect_publisher(settings.rabbitmq_dsn), timeout=5.0
        )
    except Exception:
        logger.warning("rabbitmq publisher unavailable; OTP delivery falls back to log")
        _publisher = None
    return _publisher


async def close_publisher() -> None:
    global _publisher
    if _publisher is not None:
        await _publisher.close()
        _publisher = None