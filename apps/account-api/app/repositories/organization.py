from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.medical import MembershipStatus
from app.models.organization import (
    Organization,
    OrganizationApiKey,
    OrganizationApiRequest,
    OrganizationBranch,
    OrganizationLicense,
    OrganizationMembership,
    OrganizationUploadBatch,
    OrganizationUploadBatchItem,
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

    async def list_api_keys(self, organization_id: UUID) -> list[OrganizationApiKey]:
        result = await self._session.execute(
            select(OrganizationApiKey)
            .where(OrganizationApiKey.organization_id == organization_id)
            .order_by(OrganizationApiKey.created_at, OrganizationApiKey.name)
        )
        return list(result.scalars().all())

    async def get_api_key(
        self, organization_id: UUID, key_id: UUID
    ) -> OrganizationApiKey | None:
        result = await self._session.execute(
            select(OrganizationApiKey).where(
                OrganizationApiKey.id == key_id,
                OrganizationApiKey.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def find_api_key_by_hash(self, key_hash: str) -> OrganizationApiKey | None:
        result = await self._session.execute(
            select(OrganizationApiKey)
            .where(OrganizationApiKey.key_hash == key_hash)
            .options(selectinload(OrganizationApiKey.organization))
        )
        return result.scalar_one_or_none()

    async def create_api_request(
        self, request_row: OrganizationApiRequest
    ) -> OrganizationApiRequest:
        self._session.add(request_row)
        await self._session.commit()
        return request_row

    async def list_organizations(self) -> list[Organization]:
        result = await self._session.execute(
            select(Organization).order_by(Organization.created_at, Organization.name)
        )
        return list(result.scalars().all())

    async def list_memberships(
        self, organization_id: UUID
    ) -> list[OrganizationMembership]:
        result = await self._session.execute(
            select(OrganizationMembership)
            .where(OrganizationMembership.organization_id == organization_id)
            .order_by(OrganizationMembership.joined_at, OrganizationMembership.id)
        )
        return list(result.scalars().all())

    async def get_membership(
        self, organization_id: UUID, account_id: UUID
    ) -> OrganizationMembership | None:
        result = await self._session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.account_id == account_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_active_membership(
        self, organization_id: UUID, account_id: UUID
    ) -> OrganizationMembership | None:
        """The account's ACTIVE membership in the organization, if any."""
        result = await self._session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.account_id == account_id,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
            )
        )
        return result.scalar_one_or_none()

    async def list_active_memberships_for_account(
        self, account_id: UUID
    ) -> list[OrganizationMembership]:
        """All ACTIVE memberships for the account (Phase 4b org-context base)."""
        result = await self._session.execute(
            select(OrganizationMembership)
            .where(
                OrganizationMembership.account_id == account_id,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
            )
            .order_by(OrganizationMembership.joined_at, OrganizationMembership.id)
        )
        return list(result.scalars().all())

    async def get_active_organization_for_account(
        self, account_id: UUID
    ) -> Organization | None:
        """Return the account's organization via an ACTIVE membership, if any.

        Deterministic for multi-membership accounts: the earliest ``joined_at``
        membership wins (id tie-break). ``scalars().first()`` never raises on a
        second membership (Phase 4a hardening).
        """
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
            .order_by(OrganizationMembership.joined_at, Organization.id)
        )
        return result.scalars().first()

    async def list_active_organizations_for_account(
        self, account_id: UUID
    ) -> list[Organization]:
        """All organizations with an ACTIVE membership for the account."""
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
            .order_by(OrganizationMembership.joined_at, Organization.id)
        )
        return list(result.scalars().all())

    async def find_batch_by_idempotency_key(
        self, organization_id: UUID, idempotency_key: str
    ) -> OrganizationUploadBatch | None:
        """The batch for ``(organization_id, idempotency_key)``, if any."""
        result = await self._session.execute(
            select(OrganizationUploadBatch).where(
                OrganizationUploadBatch.organization_id == organization_id,
                OrganizationUploadBatch.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def get_batch(
        self, organization_id: UUID, batch_id: UUID
    ) -> OrganizationUploadBatch | None:
        """Org-scoped batch with its items (no IDOR: foreign -> None).

        ``populate_existing`` forces a refresh even when the batch is already in
        the session identity map: the batch and its items are finalized by a
        *different* transaction (the per-item/finalize sessions), so a cached
        header must never shadow the committed counters in the caller response.
        """
        result = await self._session.execute(
            select(OrganizationUploadBatch)
            .options(selectinload(OrganizationUploadBatch.items))
            .execution_options(populate_existing=True)
            .where(
                OrganizationUploadBatch.id == batch_id,
                OrganizationUploadBatch.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_batch_items(
        self, batch_id: UUID
    ) -> list[OrganizationUploadBatchItem]:
        """Items of a batch ordered by ``item_index`` (caller gated by org)."""
        result = await self._session.execute(
            select(OrganizationUploadBatchItem)
            .where(OrganizationUploadBatchItem.batch_id == batch_id)
            .order_by(OrganizationUploadBatchItem.item_index)
        )
        return list(result.scalars().all())