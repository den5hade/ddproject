from typing import Protocol

from app.core.redis import redis_client

RATE_LIMIT_KEY_PREFIX = "rl"
WINDOW_SECONDS = 60


class RateLimitStore(Protocol):
    async def incr(self, key: str) -> int: ...

    async def expire(self, key: str, seconds: int) -> None: ...


class ApiKeyRateLimiter:
    """Per-minute counter for an API key (Phase 4c).

    Key: ``rl:{api_key_id}:{minute}``. The first hit in a minute sets a 60s
    TTL; every hit increments the counter. Once the counter exceeds
    ``integration_rate_limit_per_minute`` the caller is rate-limited (429).
    """

    def __init__(
        self,
        redis: RateLimitStore | None = None,
        *,
        limit_per_minute: int | None = None,
    ) -> None:
        self._redis = redis or redis_client
        from app.core.config import settings

        self._limit = (
            limit_per_minute
            if limit_per_minute is not None
            else settings.integration_rate_limit_per_minute
        )

    @staticmethod
    def _window_key(api_key_id: str, minute: int) -> str:
        return f"{RATE_LIMIT_KEY_PREFIX}:{api_key_id}:{minute}"

    async def allowed(self, api_key_id: str, minute: int) -> bool:
        key = self._window_key(api_key_id, minute)
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, WINDOW_SECONDS)
        return count <= self._limit