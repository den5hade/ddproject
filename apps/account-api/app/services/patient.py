import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import GrantStatus
from app.domain.medical import PatientAlreadyExistsError, PersonNotFoundError
from app.models.access_grant import PatientAccessGrant
from app.models.account import Account
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.person import Person
from app.repositories.account import AccountRepository
from app.repositories.patient import PatientRepository
from app.repositories.person import PersonRepository
from app.schemas.patient import PatientCreateRequest
from app.schemas.profile import PersonUpdate

logger = logging.getLogger("account_api.patient")


@dataclass
class PatientContext:
    patient: Patient
    person: Person
    medical_record: MedicalRecord


class PatientService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._person = PersonRepository(session)
        self._patient = PatientRepository(session)

    async def create_patient(
        self, account: Account, data: PatientCreateRequest | None = None
    ) -> PatientContext:
        if await self._patient.get_by_account(account) is not None:
            raise PatientAlreadyExistsError("account already has a patient")
        return await self._ensure(account, data)

    async def ensure_patient_for_account(
        self, account: Account, data: PatientCreateRequest | None = None
    ) -> PatientContext:
        try:
            return await self._ensure(account, data)
        except IntegrityError:
            await self._session.rollback()
            fresh = await AccountRepository(self._session).get_by_id(account.id)
            if fresh is None:
                raise PersonNotFoundError("account no longer exists") from None
            return await self._ensure(fresh, data)

    async def get_patient(self, account: Account) -> PatientContext:
        return await self.ensure_patient_for_account(account)

    async def update_person(
        self, account: Account, data: PersonUpdate
    ) -> PatientContext:
        context = await self.ensure_patient_for_account(account)
        person = context.person
        if person is None:
            raise PersonNotFoundError("no person bound to the account")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(person, field, value)
        await self._session.commit()
        return await self._build_context(context.patient)

    async def get_patient_for_view(
        self, account: Account, patient_id: UUID
    ) -> PatientContext | None:
        """Return the patient context iff the account owns it or holds an active grant."""
        patient = await self._patient.get_by_id(patient_id)
        if patient is None:
            return None
        if not self._is_owner(account, patient) and not await self._has_active_grant(
            account, patient_id
        ):
            return None
        return await self._build_context(patient)

    async def _ensure(
        self, account: Account, data: PatientCreateRequest | None
    ) -> PatientContext:
        patient = await self._patient.get_by_account(account)
        if patient is not None:
            return await self._build_context(patient)

        person = None
        if account.person_id is not None:
            person = await self._person.get(account.person_id)
        if person is None:
            person = self._new_person(data)
            await self._person.save(person)
            account.person_id = person.id
            await self._session.flush()

        patient = await self._patient.create_with_medical_record(person.id)
        await self._session.commit()
        logger.info("patient_created account_id=%s patient_id=%s", account.id, patient.id)
        return await self._build_context(patient)

    @staticmethod
    def _new_person(data: PatientCreateRequest | None) -> Person:
        person = Person()
        if data is not None and data.person is not None:
            for field, value in data.person.model_dump(exclude_unset=True).items():
                if value is None and field in {"first_name", "last_name"}:
                    continue
                setattr(person, field, value)
        return person

    async def _build_context(self, patient: Patient) -> PatientContext:
        person = await self._person.get(patient.person_id)
        if person is None:
            raise PersonNotFoundError("patient has no bound person")
        medical_record = await self._session.scalar(
            select(MedicalRecord).where(MedicalRecord.patient_id == patient.id)
        )
        if medical_record is None:
            raise PersonNotFoundError("patient has no medical record")
        return PatientContext(
            patient=patient, person=person, medical_record=medical_record
        )

    @staticmethod
    def _is_owner(account: Account, patient: Patient) -> bool:
        return account.person_id == patient.person_id

    async def _has_active_grant(self, account: Account, patient_id: UUID) -> bool:
        now = datetime.now(UTC)
        result = await self._session.scalar(
            select(PatientAccessGrant.id)
            .where(
                PatientAccessGrant.patient_id == patient_id,
                PatientAccessGrant.account_id == account.id,
                PatientAccessGrant.status == GrantStatus.ACTIVE,
                or_(
                    PatientAccessGrant.expires_at.is_(None),
                    PatientAccessGrant.expires_at > now,
                ),
            )
            .limit(1)
        )
        return result is not None


__all__ = ["PatientContext", "PatientService"]