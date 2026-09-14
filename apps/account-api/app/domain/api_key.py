import hashlib
import hmac
import secrets

from app.core.config import settings


def _api_key_env(environment: str) -> str:
    return "liv" if environment.strip().lower() == "production" else "tst"


def generate_raw_api_key() -> str:
    """Return a new raw api key: ``ddorg_<env>_<256-bit-secret>``."""
    env = _api_key_env(settings.environment)
    token = secrets.token_urlsafe(43)  # 256 bits
    return f"ddorg_{env}_{token}"


def prefix_for_raw_key(raw_key: str) -> str:
    """Return the display prefix (first 12 characters) of a raw api key."""
    return raw_key[:12]


def hash_api_key(raw_key: str) -> str:
    """Return the HMAC-SHA256 hex digest of *raw_key* (the persisted value)."""
    key_bytes = settings.integration_api_hmac_key.encode()
    return hmac.new(key_bytes, raw_key.encode(), hashlib.sha256).hexdigest()
