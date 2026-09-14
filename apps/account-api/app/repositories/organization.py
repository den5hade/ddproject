from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.medical import MembershipStatus
from app.models.organization import (
    Organization,
    OrganizationBranch,
    OrganizationLicense,
    OrganizationMembership,
)


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

    async def list_branches(self, organization_id: UUID) -> list[OrganizationBranch]:
        result = await self._session.execute(
            select(OrganizationBranch)
            .where(OrganizationBranch.organization_id == organization_id)
            .order_by(OrganizationBranch.created_at, OrganizationBranch.code)
        )
        return list(result.scalars().all())

    async def get_branch(
        self, organization_id: UUID, branch_id: UUID
    ) -> OrganizationBranch | None:
        result = await self._session.execute(
            select(OrganizationBranch).where(
                OrganizationBranch.id == branch_id,
                OrganizationBranch.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def find_branch_by_code(
        self, organization_id: UUID, code: str
    ) -> OrganizationBranch | None:
        result = await self._session.execute(
            select(OrganizationBranch).where(
                OrganizationBranch.organization_id == organization_id,
                OrganizationBranch.code == code,
            )
        )
        return result.scalar_one_or_none()

    async def list_licenses(self, organization_id: UUID) -> list[OrganizationLicense]:
        result = await self._session.execute(
            select(OrganizationLicense)
            .where(OrganizationLicense.organization_id == organization_id)
            .order_by(OrganizationLicense.created_at, OrganizationLicense.license_number)
        )
        return list(result.scalars().all())

    async def get_license(
        self, organization_id: UUID, license_id: UUID
    ) -> OrganizationLicense | None:
        result = await self._session.execute(
            select(OrganizationLicense).where(
                OrganizationLicense.id == license_id,
                OrganizationLicense.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def find_license_by_number(
        self, organization_id: UUID, license_number: str
    ) -> OrganizationLicense | None:
        result = await self._session.execute(
            select(OrganizationLicense).where(
                OrganizationLicense.organization_id == organization_id,
                OrganizationLicense.license_number == license_number,
            )
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