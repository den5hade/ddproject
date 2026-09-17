"""Periodic retention purge for ``organization_api_requests`` (Phase 4h).

Runs as an asyncio task inside the account-api lifespan (mirrors the
consumer-task pattern). Every ``integration_api_request_purge_hours`` hours it
deletes access-log rows older than ``integration_api_request_retention_days``
in bounded batches (open decision 7). Best-effort: a failure is logged and the
loop keeps going — monitoring must never take the API down.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.core.database import async_session_factory
from app.services.organization_api_request import OrganizationApiRequestService

logger = logging.getLogger("account_api")

PURGE_INTERVAL_SECONDS = 3600


async def purge_once() -> int:
    """Single purge pass; returns the number of rows deleted."""
    cutoff = datetime.now(UTC) - timedelta(
        days=settings.integration_api_request_retention_days
    )
    async with async_session_factory() as session:
        return await OrganizationApiRequestService(session).purge_expired(cutoff)


async def run_api_request_purge() -> None:
    interval = max(1, settings.integration_api_request_purge_hours) * PURGE_INTERVAL_SECONDS
    while True:
        try:
            deleted = await purge_once()
            if deleted:
                logger.info("api_request_purge deleted=%s", deleted)
        except Exception:  # pragma: no cover - best-effort background loop
            logger.exception("api_request_purge failed; will retry")
        await asyncio.sleep(interval)


__all__ = ["purge_once", "run_api_request_purge"]