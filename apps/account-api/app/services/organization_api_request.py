from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import OrganizationApiRequest
from app.repositories.organization import OrganizationRepository


class OrganizationApiRequestService:
    """Persist a non-PII ``organization_api_requests`` access-log row (Ph4c).

    Used by the request-logging middleware for ``/integration/*`` paths. Never
    stores bodies, files, canonical JSON, patient emails or medical data.
    """

    _PURGE_BATCH_SIZE = 1000

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repos = OrganizationRepository(session)

    async def record(
        self,
        *,
        request_id: str,
        method: str,
        path: str,
        status_code: int,
        duration_ms: int,
        organization_id: UUID | None = None,
        api_key_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        error_code: str | None = None,
    ) -> OrganizationApiRequest:
        row = OrganizationApiRequest(
            organization_id=organization_id,
            api_key_id=api_key_id,
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            ip_address=ip_address,
            user_agent=user_agent,
            error_code=error_code,
        )
        return await self._repos.create_api_request(row)

    async def purge_expired(self, cutoff: datetime) -> int:
        """Delete access-log rows older than *cutoff* in bounded batches.

        Retention purge (open decision 7): never one giant delete — each pass
        removes at most ``_PURGE_BATCH_SIZE`` rows. Returns the total deleted.
        """
        total = 0
        while True:
            deleted = await self._repos.purge_api_requests_older_than(
                cutoff, self._PURGE_BATCH_SIZE
            )
            if deleted == 0:
                return total
            total += deleted


__all__ = ["OrganizationApiRequestService"]