from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.patient import PatientService


async def get_patient_service(session: AsyncSession = Depends(get_db)) -> PatientService:
    return PatientService(session)


PatientServiceDep = Annotated[PatientService, Depends(get_patient_service)]