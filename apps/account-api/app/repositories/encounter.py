from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.medical import EncounterStatus, EncounterType
from app.models.encounter import Encounter


class EncounterRepository:
    """SQL access for ``encounters``; never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        medical_record_id: UUID,
        specialist_id: UUID | None,
        organization_id: UUID | None,
        type: EncounterType,
        status: EncounterStatus,
        started_at: datetime,
        reason: str | None,
        summary: str | None,
    ) -> Encounter:
        encounter = Encounter(
            medical_record_id=medical_record_id,
            specialist_id=specialist_id,
            organization_id=organization_id,
            type=type,
            status=status,
            started_at=started_at,
            reason=reason,
            summary=summary,
        )
        self._session.add(encounter)
        await self._session.flush()
        return encounter

    async def get(self, encounter_id: UUID) -> Encounter | None:
        return await self._session.get(Encounter, encounter_id)

    async def list_by_medical_record(self, medical_record_id: UUID) -> list[Encounter]:
        result = await self._session.execute(
            select(Encounter)
            .where(Encounter.medical_record_id == medical_record_id)
            .order_by(Encounter.started_at.desc())
        )
        return list(result.scalars().all())

    async def update(self, encounter: Encounter, **fields) -> Encounter:
        for field, value in fields.items():
            setattr(encounter, field, value)
        await self._session.flush()
        return encounter
