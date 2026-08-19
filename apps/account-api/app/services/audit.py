import logging
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import AuditAction
from app.models.audit_log import AuditLog
from app.repositories.audit import AuditLogRepository

logger = logging.getLogger("account_api.audit")


class AuditService:
    """Append-only audit writer; commits by default so read-only paths persist."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditLogRepository(session)

    @staticmethod
    def _client_from_request(request: Request | None) -> tuple[str, str]:
        if request is None:
            return "", ""
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            ip_address = forwarded_for.split(",")[0].strip()
        else:
            ip_address = request.client.host if request.client else ""
        return ip_address, request.headers.get("user-agent", "")

    async def record(
        self,
        *,
        action: AuditAction,
        resource_type: str = "",
        resource_id: UUID | None = None,
        patient_id: UUID | None = None,
        actor_account_id: UUID | None = None,
        request: Request | None = None,
        metadata: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        commit: bool = True,
    ) -> AuditLog:
        if ip_address is None or user_agent is None:
            ip, ua = self._client_from_request(request)
            ip_address = ip_address if ip_address is not None else ip
            user_agent = user_agent if user_agent is not None else ua
        entry = AuditLog(
            actor_account_id=actor_account_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            patient_id=patient_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata_=metadata,
        )
        await self._audit.record(entry)
        if commit:
            await self._session.commit()
        logger.info(
            "audit_recorded action=%s actor=%s patient=%s resource=%s",
            action.value,
            actor_account_id,
            patient_id,
            resource_id,
        )
        return entry

    async def list_logs(
        self,
        *,
        patient_id: UUID | None = None,
        actor_account_id: UUID | None = None,
        action: AuditAction | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:
        return await self._audit.query(
            patient_id=patient_id,
            actor_account_id=actor_account_id,
            action=action,
            limit=limit,
            offset=offset,
        )


__all__ = ["AuditService"]
