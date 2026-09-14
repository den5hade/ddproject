from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_account
from app.dependencies.rbac import require_roles
from app.domain.account import RoleCode
from app.models.account import Account
from app.models.organization import Organization
from app.repositories.organization import OrganizationRepository
from app.services.organization import OrganizationService
from app.services.organization_api_key import OrganizationApiKeyService


async def get_organization_service(
    session: AsyncSession = Depends(get_db),
) -> OrganizationService:
    return OrganizationService(session)


async def get_current_organization(
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> Organization:
    """Resolve the account's organization via an ACTIVE membership."""
    organization = await OrganizationRepository(
        session
    ).get_active_organization_for_account(account.id)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="no active organization membership",
        )
    return organization


_require_org_admin_role = require_roles(RoleCode.ORGANIZATION_ADMIN)


async def _resolve_organization_admin_membership(
    account: Account = Depends(_require_org_admin_role),
    session: AsyncSession = Depends(get_db),
) -> Organization:
    """Org resolution shared by the `OrganizationAdmin` dependency.

    Reuses the existing RBAC role check and resolves the organization through
    the account's ACTIVE membership (no active membership -> 403).
    """
    organization = await OrganizationRepository(
        session
    ).get_active_organization_for_account(account.id)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="no active organization membership",
        )
    return organization


def require_organization_admin() -> Callable[..., Organization]:
    """Return a dependency requiring the org_admin role + active membership."""
    return _resolve_organization_admin_membership


async def get_organization_api_key_service(
    session: AsyncSession = Depends(get_db),
) -> OrganizationApiKeyService:
    return OrganizationApiKeyService(session)


CurrentOrganization = Annotated[Organization, Depends(get_current_organization)]
OrganizationAdmin = Annotated[
    Organization, Depends(_resolve_organization_admin_membership)
]
OrganizationServiceDep = Annotated[
    OrganizationService, Depends(get_organization_service)
]
OrganizationApiKeyServiceDep = Annotated[
    OrganizationApiKeyService, Depends(get_organization_api_key_service)
]