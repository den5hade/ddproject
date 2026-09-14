from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.medical import MembershipStatus
from app.models.organization import Organization, OrganizationMembership


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, organization_id: UUID) -> Organization | None:
        return await self._session.get(Organization, organization_id)

    async def find_by_inn(self, inn: str) -> Organization | None:
        result = await self._session.execute(
            select(Organization).where(Organization.inn == inn)
        )
        return result.scalar_one_or_none()

    async def find_by_ogrn(self, ogrn: str) -> Organization | None:
        result = await self._session.execute(
            select(Organization).where(Organization.ogrn == ogrn)
        )
        return result.scalar_one_or_none()

    async def get_active_organization_for_account(
        self, account_id: UUID
    ) -> Organization | None:
        """Return the account's organization via an ACTIVE membership, if any."""
        result = await self._session.execute(
            select(Organization)
            .join(
                OrganizationMembership,
                OrganizationMembership.organization_id == Organization.id,
            )
            .where(
                OrganizationMembership.account_id == account_id,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
            )
        )
        return result.scalar_one_or_none()