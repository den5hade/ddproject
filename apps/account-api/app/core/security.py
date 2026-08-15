import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from app.core.config import settings
from app.domain.user_type import UserType

ACCESS_TOKEN_TYPE = "access"


class InvalidTokenError(Exception):
    """The token is malformed, signed with a wrong key, or malformed claims."""


class ExpiredTokenError(InvalidTokenError):
    """The token has expired."""


def create_access_token(
    user_id: UUID,
    user_type: UserType,
    session_id: UUID,
    expires_minutes: int | None = None,
) -> str:
    now = datetime.now(UTC)
    expire_minutes = expires_minutes or settings.jwt_access_expire_minutes
    payload = {
        "sub": str(user_id),
        "user_type": user_type.value,
        "sid": str(session_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as exc:
        raise ExpiredTokenError("access token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError("invalid access token") from exc
    if claims.get("type") != ACCESS_TOKEN_TYPE:
        raise InvalidTokenError("not an access token")
    return claims


def generate_refresh_token() -> str:
    """Opaque, high-entropy refresh token (never stored in plain text)."""
    return secrets.token_urlsafe(64)


def hash_refresh_token(token: str) -> str:
    """HMAC-SHA256 of the refresh token using the configured HMAC key."""
    return hmac.new(
        settings.auth_hmac_key.encode(),
        token.encode(),
        hashlib.sha256,
    ).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def generate_otp(length: int = 6) -> str:
    """Cryptographically-random numeric one-time code."""
    return f"{secrets.randbelow(10**length):0{length}d}"