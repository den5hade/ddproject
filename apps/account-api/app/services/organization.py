import logging
from datetime import date
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import AuditAction
from app.domain.organization import (
    BranchStatus,
    OrganizationBranchConflictError,
    OrganizationBranchNotFoundError,
    OrganizationLegalDataConflictError,
    OrganizationLicenseConflictError,
    OrganizationLicenseNotFoundError,
    OrganizationLicenseStatus,
    OrganizationNotFoundError,
    OrganizationVerificationStatus,
)
from app.models.organization import Organization, OrganizationBranch, OrganizationLicense
from app.repositories.organization import OrganizationRepository
from app.schemas.organization import (
    BranchCreate,
    BranchUpdate,
    LicenseCreate,
    LicenseUpdate,
    OrganizationUpdate,
)
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

    async def list_licenses(self, organization_id: UUID) -> list[OrganizationLicense]:
        await self._expire_overdue(organization_id)
        return await self._organizations.list_licenses(organization_id)

    async def get_license(
        self, organization_id: UUID, license_id: UUID
    ) -> OrganizationLicense:
        license = await self._organizations.get_license(organization_id, license_id)
        if license is None:
            raise OrganizationLicenseNotFoundError("license not found")
        if await self._expire_overdue(organization_id):
            return await self._organizations.get_license(organization_id, license_id)
        return license

    async def create_license(
        self,
        organization_id: UUID,
        actor_account_id: UUID,
        data: LicenseCreate,
        request: Request | None = None,
    ) -> OrganizationLicense:
        license = OrganizationLicense(
            organization_id=organization_id,
            license_number=data.license_number,
            license_type=data.license_type,
            status=data.status,
            issued_at=data.issued_at,
            expires_at=data.expires_at,
            scope=data.scope,
            issuer=data.issuer,
        )
        await self._assert_license_number_unique(organization_id, license.license_number)
        self._session.add(license)
        await self._session.commit()
        await AuditService(self._session).record(
            action=AuditAction.ORGANIZATION_LICENSE_CREATED,
            resource_type="organization_license",
            resource_id=license.id,
            actor_account_id=actor_account_id,
            request=request,
        )
        logger.info(
            "organization_license_created organization_id=%s account_id=%s license_id=%s number=%s",
            organization_id,
            actor_account_id,
            license.id,
            license.license_number,
        )
        return license

    async def update_license(
        self,
        organization_id: UUID,
        license_id: UUID,
        actor_account_id: UUID,
        data: LicenseUpdate,
        request: Request | None = None,
    ) -> OrganizationLicense:
        license = await self.get_license(organization_id, license_id)
        changes = data.model_dump(exclude_unset=True)
        number = changes.get("license_number")
        if number is not None and number != license.license_number:
            await self._assert_license_number_unique(organization_id, number)
        for field, value in changes.items():
            setattr(license, field, value)
        await self._session.commit()
        await AuditService(self._session).record(
            action=AuditAction.ORGANIZATION_LICENSE_UPDATED,
            resource_type="organization_license",
            resource_id=license.id,
            actor_account_id=actor_account_id,
            request=request,
            metadata={"fields": sorted(changes.keys())},
        )
        logger.info(
            "organization_license_updated organization_id=%s account_id=%s license_id=%s fields=%s",
            organization_id,
            actor_account_id,
            license.id,
            sorted(changes.keys()),
        )
        return license

    async def deactivate_license(
        self,
        organization_id: UUID,
        license_id: UUID,
        actor_account_id: UUID,
        request: Request | None = None,
    ) -> None:
        license = await self.get_license(organization_id, license_id)
        license.status = OrganizationLicenseStatus.REVOKED
        await self._session.commit()
        await AuditService(self._session).record(
            action=AuditAction.ORGANIZATION_LICENSE_DEACTIVATED,
            resource_type="organization_license",
            resource_id=license.id,
            actor_account_id=actor_account_id,
            request=request,
        )
        logger.info(
            "organization_license_deactivated organization_id=%s account_id=%s license_id=%s",
            organization_id,
            actor_account_id,
            license.id,
        )

    async def _assert_license_number_unique(
        self, organization_id: UUID, license_number: str
    ) -> None:
        existing = await self._organizations.find_license_by_number(
            organization_id, license_number
        )
        if existing is not None:
            raise OrganizationLicenseConflictError(
                "a license with this number already exists in the organization"
            )

    async def _expire_overdue(self, organization_id: UUID) -> bool:
        """Transition past-due ACTIVE licenses to EXPIRED (history preserved).

        Runs a commit only when at least one license actually expired; returns
        whether anything changed so read paths can refresh a stale instance.
        """
        result = await self._session.execute(
            select(OrganizationLicense).where(
                OrganizationLicense.organization_id == organization_id,
                OrganizationLicense.status == OrganizationLicenseStatus.ACTIVE,
                OrganizationLicense.expires_at.is_not(None),
                OrganizationLicense.expires_at < date.today(),
            )
        )
        overdue = list(result.scalars().all())
        if not overdue:
            return False
        for license in overdue:
            license.status = OrganizationLicenseStatus.EXPIRED
        await self._session.commit()
        return True


__all__ = ["OrganizationService"]