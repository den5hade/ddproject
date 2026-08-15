import redis.asyncio as aioredis

from app.core.config import settings

redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)


async def close_redis() -> None:
    await redis_client.aclose()