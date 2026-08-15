from typing import Protocol

from app.core.redis import redis_client
from app.core.security import constant_time_equals, generate_otp

OTP_TTL_SECONDS = 300  # 5 minutes
OTP_MAX_ATTEMPTS = 5
OTP_REQUEST_WINDOW_SECONDS = 60
OTP_MAX_REQUESTS_PER_WINDOW = 1

OTP_KEY_PREFIX = "otp:code"
OTP_ATTEMPTS_KEY_PREFIX = "otp:attempts"
OTP_RATELIMIT_KEY_PREFIX = "otp:ratelimit"


class OtpStore(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ex: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def incr(self, key: str) -> int: ...

    async def expire(self, key: str, seconds: int) -> None: ...


class OtpService:
    """One-time login codes stored in Redis with TTL, attempts and rate limits."""

    def __init__(self, redis: OtpStore | None = None) -> None:
        self._redis = redis or redis_client
        self._ttl = OTP_TTL_SECONDS
        self._max_attempts = OTP_MAX_ATTEMPTS

    @staticmethod
    def _code_key(identity: str) -> str:
        return f"{OTP_KEY_PREFIX}:{identity}"

    @staticmethod
    def _attempts_key(identity: str) -> str:
        return f"{OTP_ATTEMPTS_KEY_PREFIX}:{identity}"

    @staticmethod
    def _ratelimit_key(identity: str) -> str:
        return f"{OTP_RATELIMIT_KEY_PREFIX}:{identity}"

    async def can_request(self, identity: str) -> bool:
        key = self._ratelimit_key(identity)
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, OTP_REQUEST_WINDOW_SECONDS)
        return count <= OTP_MAX_REQUESTS_PER_WINDOW

    async def issue(self, identity: str) -> str:
        code = generate_otp()
        await self._redis.set(self._code_key(identity), code, ex=self._ttl)
        await self._redis.delete(self._attempts_key(identity))
        return code

    async def verify(self, identity: str, code: str) -> bool:
        stored = await self._redis.get(self._code_key(identity))
        if stored is None:
            return False

        if not constant_time_equals(stored, code):  # type: ignore
            attempts_key = self._attempts_key(identity)
            attempts = await self._redis.incr(attempts_key)
            if attempts == 1:
                await self._redis.expire(attempts_key, self._ttl)
            if attempts >= self._max_attempts:
                await self._redis.delete(self._code_key(identity))
            return False

        await self._redis.delete(self._code_key(identity))
        await self._redis.delete(self._attempts_key(identity))
        return True
