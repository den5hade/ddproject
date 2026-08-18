from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient


class PatientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, person_id: UUID) -> Patient:
        patient = Patient(person_id=person_id)
        self._session.add(patient)
        await self._session.flush()
        return patient

    async def create_with_medical_record(self, person_id: UUID) -> Patient:
        """Create a Patient together with its 1:1 MedicalRecord in one transaction."""
        patient = Patient(person_id=person_id)
        self._session.add(patient)
        await self._session.flush()
        self._session.add(MedicalRecord(patient_id=patient.id))
        await self._session.flush()
        return patient

    async def get_by_id(self, patient_id: UUID) -> Patient | None:
        return await self._session.get(Patient, patient_id)

    async def get_by_person_id(self, person_id: UUID) -> Patient | None:
        result = await self._session.execute(
            select(Patient).where(Patient.person_id == person_id)
        )
        return result.scalar_one_or_none()

    async def get_by_account(self, account: Account) -> Patient | None:
        if account.person_id is None:
            return None
        return await self.get_by_person_id(account.person_id)