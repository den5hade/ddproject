from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import AuditAction
from app.models.audit_log import AuditLog


class AuditLogRepository:
    """Append-only SQL access for ``audit_logs``; never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, entry: AuditLog) -> AuditLog:
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def query(
        self,
        *,
        patient_id: UUID | None = None,
        actor_account_id: UUID | None = None,
        action: AuditAction | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:
        query = select(AuditLog).order_by(AuditLog.created_at.desc())
        if patient_id is not None:
            query = query.where(AuditLog.patient_id == patient_id)
        if actor_account_id is not None:
            query = query.where(AuditLog.actor_account_id == actor_account_id)
        if action is not None:
            query = query.where(AuditLog.action == action)
        result = await self._session.execute(query.limit(limit).offset(offset))
        return list(result.scalars().all())
