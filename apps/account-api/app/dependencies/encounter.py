from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.encounter import EncounterService


async def get_encounter_service(session: AsyncSession = Depends(get_db)) -> EncounterService:
    return EncounterService(session)


EncounterServiceDep = Annotated[EncounterService, Depends(get_encounter_service)]
