import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.medical import EncounterNotFoundError, EncounterStatus
from app.models.account import Account
from app.models.document import Document
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord
from app.models.organization import MembershipStatus, OrganizationMembership
from app.models.patient import Patient
from app.models.specialist import Specialist
from app.repositories.document import DocumentRepository
from app.repositories.encounter import EncounterRepository
from app.schemas.encounter import EncounterCreate, EncounterUpdate

logger = logging.getLogger("account_api.encounter")


class EncounterService:
    """Encounter lifecycle; access is enforced by the ABAC dependency."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._encounters = EncounterRepository(session)
        self._documents = DocumentRepository(session)

    async def create_encounter(
        self, account: Account, patient_id: UUID, data: EncounterCreate
    ) -> Encounter:
        patient, medical_record = await self._patient_and_record(patient_id)
        specialist_id = await self._specialist_id_for(account)
        organization_id = await self._organization_id_for(account)
        encounter = await self._encounters.create(
            medical_record_id=medical_record.id,
            specialist_id=specialist_id,
            organization_id=organization_id,
            type=data.type,
            status=EncounterStatus.SCHEDULED,
            started_at=data.started_at,
            reason=data.reason,
            summary=data.summary,
        )
        await self._session.commit()
        logger.info(
            "encounter_created encounter_id=%s patient_id=%s",
            encounter.id,
            patient.id,
        )
        return encounter

    async def list_encounters(self, patient_id: UUID) -> list[Encounter]:
        _patient, medical_record = await self._patient_and_record(patient_id)
        return await self._encounters.list_by_medical_record(medical_record.id)

    async def get_encounter(self, encounter_id: UUID) -> Encounter:
        encounter = await self._encounters.get(encounter_id)
        if encounter is None:
            raise EncounterNotFoundError("encounter not found")
        return encounter

    async def update_encounter(
        self, encounter_id: UUID, data: EncounterUpdate
    ) -> Encounter:
        encounter = await self._encounters.get(encounter_id)
        if encounter is None:
            raise EncounterNotFoundError("encounter not found")
        await self._encounters.update(
            encounter, **data.model_dump(exclude_unset=True)
        )
        await self._session.commit()
        logger.info("encounter_updated encounter_id=%s", encounter.id)
        return encounter

    async def list_encounter_documents(self, encounter_id: UUID) -> list[Document]:
        encounter = await self.get_encounter(encounter_id)
        return await self._documents.list_by_encounter(encounter.id)

    # ---------------------------------------------------------------- helpers
    async def _patient_and_record(
        self, patient_id: UUID
    ) -> tuple[Patient, MedicalRecord]:
        patient = await self._session.get(Patient, patient_id)
        if patient is None:
            raise EncounterNotFoundError("patient not found")
        medical_record = await self._session.scalar(
            select(MedicalRecord).where(MedicalRecord.patient_id == patient_id)
        )
        if medical_record is None:
            raise EncounterNotFoundError("patient has no medical record")
        return patient, medical_record

    async def _specialist_id_for(self, account: Account) -> UUID | None:
        if account.person_id is None:
            return None
        specialist = await self._session.scalar(
            select(Specialist).where(Specialist.person_id == account.person_id)
        )
        return specialist.id if specialist is not None else None

    async def _organization_id_for(self, account: Account) -> UUID | None:
        membership = await self._session.scalar(
            select(OrganizationMembership)
            .where(
                OrganizationMembership.account_id == account.id,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
            )
            .order_by(OrganizationMembership.joined_at.desc())
            .limit(1)
        )
        return membership.organization_id if membership is not None else None


__all__ = ["EncounterService"]
