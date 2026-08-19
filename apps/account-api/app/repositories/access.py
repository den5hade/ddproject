from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import AccessReason, GrantStatus
from app.models.access_grant import PatientAccessGrant


class AccessGrantRepository:
    """SQL access for ``patient_access_grants``; never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        patient_id: UUID,
        account_id: UUID,
        granted_by_account_id: UUID,
        organization_id: UUID | None = None,
        can_view_documents: bool = False,
        can_upload_documents: bool = False,
        can_view_extractions: bool = False,
        can_view_analytics: bool = False,
        can_create_encounters: bool = False,
        can_edit_medical_data: bool = False,
        status: GrantStatus = GrantStatus.ACTIVE,
        access_reason: AccessReason | None = None,
        expires_at: datetime | None = None,
    ) -> PatientAccessGrant:
        grant = PatientAccessGrant(
            patient_id=patient_id,
            account_id=account_id,
            granted_by_account_id=granted_by_account_id,
            organization_id=organization_id,
            can_view_documents=can_view_documents,
            can_upload_documents=can_upload_documents,
            can_view_extractions=can_view_extractions,
            can_view_analytics=can_view_analytics,
            can_create_encounters=can_create_encounters,
            can_edit_medical_data=can_edit_medical_data,
            status=status,
            access_reason=access_reason.value if access_reason is not None else None,
            expires_at=expires_at,
        )
        self._session.add(grant)
        await self._session.flush()
        return grant

    async def get(self, grant_id: UUID) -> PatientAccessGrant | None:
        return await self._session.get(PatientAccessGrant, grant_id)

    async def get_for_patient(
        self, patient_id: UUID, grant_id: UUID
    ) -> PatientAccessGrant | None:
        return await self._session.scalar(
            select(PatientAccessGrant).where(
                PatientAccessGrant.id == grant_id,
                PatientAccessGrant.patient_id == patient_id,
            )
        )

    async def list_by_patient(self, patient_id: UUID) -> list[PatientAccessGrant]:
        result = await self._session.execute(
            select(PatientAccessGrant)
            .where(PatientAccessGrant.patient_id == patient_id)
            .order_by(PatientAccessGrant.created_at.desc())
        )
        return list(result.scalars().all())

    async def find_active_for(
        self,
        patient_id: UUID,
        account_id: UUID,
        flag: str | None = None,
    ) -> PatientAccessGrant | None:
        now = datetime.now(UTC)
        query = select(PatientAccessGrant).where(
            PatientAccessGrant.patient_id == patient_id,
            PatientAccessGrant.account_id == account_id,
            PatientAccessGrant.status == GrantStatus.ACTIVE,
            or_(
                PatientAccessGrant.expires_at.is_(None),
                PatientAccessGrant.expires_at > now,
            ),
        )
        if flag is not None:
            query = query.where(getattr(PatientAccessGrant, flag).is_(True))
        return await self._session.scalar(
            query.order_by(PatientAccessGrant.created_at.desc()).limit(1)
        )

    async def update(self, grant: PatientAccessGrant, **fields) -> PatientAccessGrant:
        for field, value in fields.items():
            setattr(grant, field, value)
        await self._session.flush()
        return grant

    async def revoke(self, grant: PatientAccessGrant) -> PatientAccessGrant:
        grant.status = GrantStatus.REVOKED
        await self._session.flush()
        return grant
