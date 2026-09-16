from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.account import IdentityKind
from app.domain.identity import Identity
from app.domain.organization import InvalidPatientIdentityError
from app.repositories.account import AccountRepository
from app.services.patient import PatientContext, PatientService


@dataclass(frozen=True)
class ResolvedPatient:
    patient_id: UUID
    medical_record_id: UUID
    account_id: UUID


class OrganizationPatientResolver:
    """Resolve the integration payload's ``patient_email`` to a medical record.

    Organizations address patients by email. The resolver parses and
    canonicalizes the email identity, lazily creating a PENDING account when
    the email is unknown, and (re)creating the 1:1 patient + medical record via
    ``PatientService.ensure_patient_for_account``. Concurrent submissions for
    the same email are reconciled transactionally (IntegrityError -> rollback ->
    reload -> retry), mirroring ``PatientService.ensure_patient_for_account``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._accounts = AccountRepository(session)
        self._patients = PatientService(session)

    async def resolve_by_email(self, email: str) -> ResolvedPatient:
        identity = self._parse_email(email)
        try:
            account, _ = await self._accounts.get_or_create_by_identity(
                identity.canonical
            )
            return await self._resolve_for(account)
        except IntegrityError:
            await self._session.rollback()
            fresh = await self._accounts.get_by_identity(identity.canonical)
            if fresh is None:
                raise InvalidPatientIdentityError(
                    "could not resolve the patient identity (account conflict)"
                ) from None
            return await self._resolve_for(fresh)

    async def _resolve_for(self, account) -> ResolvedPatient:
        context: PatientContext = await self._patients.ensure_patient_for_account(
            account
        )
        return ResolvedPatient(
            patient_id=context.patient.id,
            medical_record_id=context.medical_record.id,
            account_id=account.id,
        )

    @staticmethod
    def _parse_email(email: str) -> Identity:
        try:
            identity = Identity.parse(email)
        except ValueError as exc:
            raise InvalidPatientIdentityError(str(exc)) from None
        if identity.kind is not IdentityKind.EMAIL:
            raise InvalidPatientIdentityError(
                "organization integration addresses patients by email only"
            )
        return identity


__all__ = ["OrganizationPatientResolver", "ResolvedPatient"]