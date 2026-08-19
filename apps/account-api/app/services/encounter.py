import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import GrantStatus
from app.domain.medical import (
    EncounterAccessDeniedError,
    EncounterNotFoundError,
    EncounterStatus,
)
from app.models.access_grant import PatientAccessGrant
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
    """Encounter lifecycle; access checks are inline until M5 ABAC."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._encounters = EncounterRepository(session)
        self._documents = DocumentRepository(session)

    async def create_encounter(
        self, account: Account, patient_id: UUID, data: EncounterCreate
    ) -> Encounter:
        patient, medical_record = await self._patient_and_record(patient_id)
        if not self._is_owner(account, patient) and not await self._has_active_grant(
            account, patient.id, "can_create_encounters"
        ):
            raise EncounterAccessDeniedError(
                "no permission to create encounters for this patient"
            )
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

    async def list_encounters(
        self, account: Account, patient_id: UUID
    ) -> list[Encounter] | None:
        patient, medical_record = await self._patient_and_record(patient_id)
        if not self._is_owner(account, patient) and not await self._has_active_grant(
            account, patient.id
        ):
            return None
        return await self._encounters.list_by_medical_record(medical_record.id)

    async def get_encounter(
        self, account: Account, encounter_id: UUID
    ) -> Encounter:
        encounter = await self._encounters.get(encounter_id)
        if encounter is None:
            raise EncounterNotFoundError("encounter not found")
        patient = await self._encounter_patient(encounter)
        if patient is None or (
            not self._is_owner(account, patient)
            and not await self._has_active_grant(account, patient.id)
        ):
            raise EncounterAccessDeniedError("no access to this encounter")
        return encounter

    async def update_encounter(
        self, account: Account, encounter_id: UUID, data: EncounterUpdate
    ) -> Encounter:
        encounter = await self._encounters.get(encounter_id)
        if encounter is None:
            raise EncounterNotFoundError("encounter not found")
        patient = await self._encounter_patient(encounter)
        if patient is None or (
            not self._is_owner(account, patient)
            and not await self._has_active_grant(account, patient.id, "can_edit_medical_data")
        ):
            raise EncounterAccessDeniedError("no permission to edit this encounter")
        await self._encounters.update(
            encounter, **data.model_dump(exclude_unset=True)
        )
        await self._session.commit()
        logger.info("encounter_updated encounter_id=%s", encounter.id)
        return encounter

    async def list_encounter_documents(
        self, account: Account, encounter_id: UUID
    ) -> list[Document]:
        encounter = await self.get_encounter(account, encounter_id)
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

    async def _encounter_patient(self, encounter: Encounter) -> Patient | None:
        medical_record = await self._session.get(
            MedicalRecord, encounter.medical_record_id
        )
        if medical_record is None:
            return None
        return await self._session.get(Patient, medical_record.patient_id)

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

    async def _has_active_grant(
        self, account: Account, patient_id: UUID, flag: str | None = None
    ) -> bool:
        now = datetime.now(UTC)
        query = select(1).where(
            PatientAccessGrant.patient_id == patient_id,
            PatientAccessGrant.account_id == account.id,
            PatientAccessGrant.status == GrantStatus.ACTIVE,
            or_(
                PatientAccessGrant.expires_at.is_(None),
                PatientAccessGrant.expires_at > now,
            ),
        )
        if flag is not None:
            query = query.where(getattr(PatientAccessGrant, flag).is_(True))
        result = await self._session.scalar(query.limit(1))
        return result is not None

    @staticmethod
    def _is_owner(account: Account, patient: Patient) -> bool:
        return account.person_id == patient.person_id


__all__ = ["EncounterService"]
