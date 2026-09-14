import logging
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import AuditAction
from app.domain.organization import (
    OrganizationLegalDataConflictError,
    OrganizationNotFoundError,
    OrganizationVerificationStatus,
)
from app.models.organization import Organization
from app.repositories.organization import OrganizationRepository
from app.schemas.organization import OrganizationUpdate
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


__all__ = ["OrganizationService"]