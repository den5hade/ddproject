import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import (
    AuditAction,
    GrantStatus,
    PatientAccessGrantNotFoundError,
)
from app.domain.account import AccountStatus, RoleCode
from app.models.access_grant import PatientAccessGrant
from app.models.account import Account
from app.models.patient import Patient
from app.repositories.access import AccessGrantRepository
from app.repositories.rbac import RbacRepository
from app.schemas.access import AccessGrantCreate, AccessGrantUpdate
from app.services.audit import AuditService

logger = logging.getLogger("account_api.access")


class AccessService:
    """Access-grant management and the ABAC decision core for medical data."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._grants = AccessGrantRepository(session)
        self._audit = AuditService(session)

    async def grant(
        self, *, actor: Account, patient_id: UUID, data: AccessGrantCreate
    ) -> PatientAccessGrant:
        grant = await self._grants.create(
            patient_id=patient_id,
            account_id=data.account_id,
            granted_by_account_id=actor.id,
            organization_id=data.organization_id,
            can_view_documents=data.can_view_documents,
            can_upload_documents=data.can_upload_documents,
            can_view_extractions=data.can_view_extractions,
            can_view_analytics=data.can_view_analytics,
            can_create_encounters=data.can_create_encounters,
            can_edit_medical_data=data.can_edit_medical_data,
            access_reason=data.access_reason,
            expires_at=data.expires_at,
        )
        await self._audit.record(
            action=AuditAction.GRANT_ACCESS,
            resource_type="patient",
            resource_id=patient_id,
            patient_id=patient_id,
            actor_account_id=actor.id,
            metadata={"grant_id": str(grant.id)},
            commit=False,
        )
        await self._session.commit()
        logger.info(
            "access_granted patient_id=%s grant_id=%s by=%s",
            patient_id,
            grant.id,
            actor.id,
        )
        return grant

    async def update_grant(
        self,
        *,
        actor: Account,
        patient_id: UUID,
        grant_id: UUID,
        data: AccessGrantUpdate,
    ) -> PatientAccessGrant:
        grant = await self._grants.get_for_patient(patient_id, grant_id)
        if grant is None:
            raise PatientAccessGrantNotFoundError("access grant not found")
        fields = data.model_dump(exclude_unset=True)
        if fields.get("access_reason") is not None:
            fields["access_reason"] = fields["access_reason"].value
        await self._grants.update(grant, **fields)
        await self._audit.record(
            action=AuditAction.GRANT_ACCESS,
            resource_type="patient",
            resource_id=patient_id,
            patient_id=patient_id,
            actor_account_id=actor.id,
            metadata={"grant_id": str(grant.id), "updated": True},
            commit=False,
        )
        await self._session.commit()
        logger.info("access_grant_updated grant_id=%s", grant.id)
        return grant

    async def revoke(
        self, *, actor: Account, patient_id: UUID, grant_id: UUID
    ) -> PatientAccessGrant:
        grant = await self._grants.get_for_patient(patient_id, grant_id)
        if grant is None:
            raise PatientAccessGrantNotFoundError("access grant not found")
        if grant.status != GrantStatus.REVOKED:
            await self._grants.revoke(grant)
            await self._audit.record(
                action=AuditAction.REVOKE_ACCESS,
                resource_type="patient",
                resource_id=patient_id,
                patient_id=patient_id,
                actor_account_id=actor.id,
                metadata={"grant_id": str(grant.id)},
                commit=False,
            )
            await self._session.commit()
            logger.info("access_revoked grant_id=%s by=%s", grant.id, actor.id)
        return grant

    async def list_grants(self, *, patient_id: UUID) -> list[PatientAccessGrant]:
        return await self._grants.list_by_patient(patient_id)

    async def allows(
        self,
        *,
        account: Account,
        patient: Patient,
        flag: str | None = None,
    ) -> bool:
        """Owner, or a specialist with an active grant carrying the flag.

        Rule (§33): account active AND (owner OR specialist role) AND
        active grant with the required flag and a valid ``expires_at``.
        """
        if account.status != AccountStatus.ACTIVE:
            return False
        if account.person_id == patient.person_id:
            return True
        if not await self._has_role(account.id, RoleCode.SPECIALIST):
            return False
        grant = await self._grants.find_active_for(patient.id, account.id, flag)
        return grant is not None

    async def _has_role(self, account_id: UUID, code: RoleCode) -> bool:
        roles = await RbacRepository(self._session).list_account_roles(account_id)
        return any(role.code == code.value for role in roles)


__all__ = ["AccessService"]
