from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_account
from app.domain.organization import OrganizationMembershipRole
from app.models.account import Account
from app.models.organization import Organization, OrganizationMembership
from app.repositories.organization import OrganizationRepository
from app.services.organization import OrganizationService
from app.services.organization_api_key import OrganizationApiKeyService
from app.services.organization_monitoring import OrganizationMonitoringService
from app.services.organization_schema import OrganizationSchemaService

_MANAGER_ROLES = frozenset(
    {OrganizationMembershipRole.OWNER, OrganizationMembershipRole.ADMIN}
)


def _is_manager(membership: OrganizationMembership) -> bool:
    return membership.role in _MANAGER_ROLES


@dataclass(frozen=True)
class OrganizationContext:
    """An account's ACTIVE membership + the resolved organization.

    Phase 4b: org authorization migrates from the legacy global
    ``organization_admin`` ``AccountRole`` to the resolved membership role
    (``owner|admin`` manage ``/organizations/me/*``).
    """

    account: Account
    organization: Organization
    membership: OrganizationMembership

    @property
    def actor_account_id(self) -> UUID:
        return self.account.id


async def get_organization_service(
    session: AsyncSession = Depends(get_db),
) -> OrganizationService:
    return OrganizationService(session)


async def _resolve_current_context(
    account: Account,
    session: AsyncSession,
    x_organization_id: str | None,
) -> OrganizationContext:
    """Resolve the account's current-organization context.

    Only ACTIVE memberships qualify. With a single membership the selection is
    implicit; with several the caller must select one explicitly via the
    ``X-Organization-Id`` header (Phase 4b — no implicit "first membership" on
    write endpoints).
    """
    repo = OrganizationRepository(session)
    memberships = await repo.list_active_memberships_for_account(account.id)
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="no active organization membership",
        )
    if len(memberships) == 1:
        membership = memberships[0]
    else:
        if x_organization_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ambiguous organization context; provide X-Organization-Id",
            )
        try:
            requested = UUID(x_organization_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid X-Organization-Id",
            ) from exc
        membership = next(
            (m for m in memberships if m.organization_id == requested), None
        )
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="organization not found"
            )
    organization = await repo.get_by_id(membership.organization_id)
    assert organization is not None
    return OrganizationContext(
        account=account, organization=organization, membership=membership
    )


async def get_my_organization(
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
    x_organization_id: str | None = Header(default=None),
) -> Organization:
    """Current org for management endpoints (``/organizations/me/*``).

    Requires an ACTIVE membership with role ``owner|admin``; ``member`` gets
    403 (role downgrade closes management access).
    """
    context = await _resolve_current_context(account, session, x_organization_id)
    if not _is_manager(context.membership):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient organization membership role",
        )
    return context.organization


async def get_my_organizations(
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> list[Organization]:
    """All organizations the account holds an ACTIVE membership in."""
    organizations = await OrganizationRepository(
        session
    ).list_active_organizations_for_account(account.id)
    if not organizations:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="no active organization membership",
        )
    return organizations


async def _resolve_scoped_context(
    account: Account,
    session: AsyncSession,
    organization_id: UUID,
) -> OrganizationContext | None:
    """The account's ACTIVE membership + org for an explicit organization id."""
    repo = OrganizationRepository(session)
    membership = await repo.get_active_membership(organization_id, account.id)
    if membership is None:
        return None
    organization = await repo.get_by_id(organization_id)
    if organization is None:
        return None
    return OrganizationContext(
        account=account, organization=organization, membership=membership
    )


async def get_scoped_organization(
    organization_id: UUID,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> Organization:
    """An organization the account holds an ACTIVE membership in (read path).

    Unknown or foreign organizations are indistinguishable: 404 (no IDOR
    existence leak).
    """
    context = await _resolve_scoped_context(account, session, organization_id)
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="organization not found"
        )
    return context.organization


async def get_scoped_organization_manager(
    organization_id: UUID,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> Organization:
    """Owner|admin scoped org context (e.g. org membership reads)."""
    context = await _resolve_scoped_context(account, session, organization_id)
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="organization not found"
        )
    if not _is_manager(context.membership):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient organization membership role",
        )
    return context.organization


async def get_organization_api_key_service(
    session: AsyncSession = Depends(get_db),
) -> OrganizationApiKeyService:
    return OrganizationApiKeyService(session)


async def get_organization_schema_service(
    session: AsyncSession = Depends(get_db),
) -> OrganizationSchemaService:
    return OrganizationSchemaService(session)


async def get_organization_monitoring_service(
    session: AsyncSession = Depends(get_db),
) -> OrganizationMonitoringService:
    return OrganizationMonitoringService(session)


OrganizationAdmin = Annotated[Organization, Depends(get_my_organization)]
MyOrganizations = Annotated[list[Organization], Depends(get_my_organizations)]
MyOrganization = Annotated[Organization, Depends(get_scoped_organization)]
OrganizationManager = Annotated[
    Organization, Depends(get_scoped_organization_manager)
]
OrganizationServiceDep = Annotated[
    OrganizationService, Depends(get_organization_service)
]
OrganizationApiKeyServiceDep = Annotated[
    OrganizationApiKeyService, Depends(get_organization_api_key_service)
]
OrganizationSchemaServiceDep = Annotated[
    OrganizationSchemaService, Depends(get_organization_schema_service)
]
OrganizationMonitoringServiceDep = Annotated[
    OrganizationMonitoringService, Depends(get_organization_monitoring_service)
]