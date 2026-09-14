import logging
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import AuditAction
from app.domain.organization import (
    BranchStatus,
    OrganizationBranchConflictError,
    OrganizationBranchNotFoundError,
    OrganizationLegalDataConflictError,
    OrganizationNotFoundError,
    OrganizationVerificationStatus,
)
from app.models.organization import Organization, OrganizationBranch
from app.repositories.organization import OrganizationRepository
from app.schemas.organization import BranchCreate, BranchUpdate, OrganizationUpdate
from app.services.audit import AuditService

logger = logging.getLogger("account_api.organization")

_LEGAL_DATA_FIELDS = frozenset({"inn", "ogrn", "legal_address"})


class OrganizationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._organizations = OrganizationRepository(session)

    async def get_organization(self, organization_id: UUID) -> Organization:
        organization = await self._organizations.get_by_id(organization_id)
        if organization is None:
            raise OrganizationNotFoundError("organization not found")
        return organization

    async def update_organization(
        self,
        organization_id: UUID,
        actor_account_id: UUID,
        data: OrganizationUpdate,
        request: Request | None = None,
    ) -> Organization:
        """Apply a PATCH to the organization and re-flag legal data for verification.

        Changing any legal field (INN/OGRN/legal address) moves the
        organization back to PENDING so the registry-verification extension
        point (phase 12) can re-verify it.
        """
        organization = await self.get_organization(organization_id)
        changes = data.model_dump(exclude_unset=True)
        if changes:
            await self._assert_legal_unique(organization, changes)
            for field, value in changes.items():
                setattr(organization, field, value)
            if _LEGAL_DATA_FIELDS.intersection(changes):
                organization.verification_status = OrganizationVerificationStatus.PENDING
        await self._session.commit()
        await AuditService(self._session).record(
            action=AuditAction.ORGANIZATION_UPDATED,
            resource_type="organization",
            resource_id=organization.id,
            actor_account_id=actor_account_id,
            request=request,
            metadata={"fields": sorted(changes.keys())},
        )
        logger.info(
            "organization_updated organization_id=%s account_id=%s fields=%s",
            organization_id,
            actor_account_id,
            sorted(changes.keys()),
        )
        return organization

    async def _assert_legal_unique(
        self, organization: Organization, changes: dict[str, object]
    ) -> None:
        inn = changes.get("inn")
        if inn is not None and inn != organization.inn:
            other = await self._organizations.find_by_inn(inn)
            if other is not None and other.id != organization.id:
                raise OrganizationLegalDataConflictError(
                    "an organization with this INN already exists"
                )
        ogrn = changes.get("ogrn")
        if ogrn is not None and ogrn != organization.ogrn:
            other = await self._organizations.find_by_ogrn(ogrn)
            if other is not None and other.id != organization.id:
                raise OrganizationLegalDataConflictError(
                    "an organization with this OGRN already exists"
                )

    async def list_branches(self, organization_id: UUID) -> list[OrganizationBranch]:
        return await self._organizations.list_branches(organization_id)

    async def get_branch(self, organization_id: UUID, branch_id: UUID) -> OrganizationBranch:
        branch = await self._organizations.get_branch(organization_id, branch_id)
        if branch is None:
            raise OrganizationBranchNotFoundError("branch not found")
        return branch

    async def create_branch(
        self,
        organization_id: UUID,
        actor_account_id: UUID,
        data: BranchCreate,
        request: Request | None = None,
    ) -> OrganizationBranch:
        branch = OrganizationBranch(
            organization_id=organization_id,
            code=data.code,
            name=data.name,
            address=data.address,
            phone=data.phone,
            status=BranchStatus.ACTIVE,
        )
        await self._assert_branch_code_unique(organization_id, branch.code)
        self._session.add(branch)
        await self._session.commit()
        await AuditService(self._session).record(
            action=AuditAction.ORGANIZATION_BRANCH_CREATED,
            resource_type="organization_branch",
            resource_id=branch.id,
            actor_account_id=actor_account_id,
            request=request,
        )
        logger.info(
            "organization_branch_created organization_id=%s account_id=%s branch_id=%s code=%s",
            organization_id,
            actor_account_id,
            branch.id,
            branch.code,
        )
        return branch

    async def update_branch(
        self,
        organization_id: UUID,
        branch_id: UUID,
        actor_account_id: UUID,
        data: BranchUpdate,
        request: Request | None = None,
    ) -> OrganizationBranch:
        branch = await self.get_branch(organization_id, branch_id)
        changes = data.model_dump(exclude_unset=True)
        code = changes.get("code")
        if code is not None and code != branch.code:
            await self._assert_branch_code_unique(organization_id, code)
        for field, value in changes.items():
            setattr(branch, field, value)
        await self._session.commit()
        await AuditService(self._session).record(
            action=AuditAction.ORGANIZATION_BRANCH_UPDATED,
            resource_type="organization_branch",
            resource_id=branch.id,
            actor_account_id=actor_account_id,
            request=request,
            metadata={"fields": sorted(changes.keys())},
        )
        logger.info(
            "organization_branch_updated organization_id=%s account_id=%s branch_id=%s fields=%s",
            organization_id,
            actor_account_id,
            branch.id,
            sorted(changes.keys()),
        )
        return branch

    async def deactivate_branch(
        self,
        organization_id: UUID,
        branch_id: UUID,
        actor_account_id: UUID,
        request: Request | None = None,
    ) -> None:
        branch = await self.get_branch(organization_id, branch_id)
        branch.status = BranchStatus.INACTIVE
        await self._session.commit()
        await AuditService(self._session).record(
            action=AuditAction.ORGANIZATION_BRANCH_DEACTIVATED,
            resource_type="organization_branch",
            resource_id=branch.id,
            actor_account_id=actor_account_id,
            request=request,
        )
        logger.info(
            "organization_branch_deactivated organization_id=%s account_id=%s branch_id=%s",
            organization_id,
            actor_account_id,
            branch.id,
        )

    async def _assert_branch_code_unique(
        self, organization_id: UUID, code: str
    ) -> None:
        existing = await self._organizations.find_branch_by_code(organization_id, code)
        if existing is not None:
            raise OrganizationBranchConflictError(
                "a branch with this code already exists in the organization"
            )


__all__ = ["OrganizationService"]