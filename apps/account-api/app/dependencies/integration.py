from collections.abc import Callable, Coroutine
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domain.access import AuditAction
from app.domain.api_key import hash_api_key
from app.domain.medical import OrganizationStatus
from app.domain.organization import (
    OrganizationApiKeyScope,
    OrganizationApiKeyStatus,
    OrganizationVerificationStatus,
)
from app.models.organization import Organization, OrganizationApiKey
from app.repositories.organization import OrganizationRepository
from app.services.audit import AuditService
from app.services.rate_limit import ApiKeyRateLimiter

integration_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class OrganizationApiContext:
    """Authenticated integration context for an org API key (Phase 4c)."""

    organization: Organization
    api_key: OrganizationApiKey
    permissions: frozenset[str]

    @property
    def organization_id(self) -> UUID:
        return self.organization.id

    @property
    def api_key_id(self) -> UUID:
        return self.api_key.id


def get_api_key_rate_limiter() -> ApiKeyRateLimiter:
    return ApiKeyRateLimiter()


ApiKeyRateLimiterDep = Annotated[ApiKeyRateLimiter, Depends(get_api_key_rate_limiter)]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _raise_401(detail: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _record_api_key_auth_failed(
    session: AsyncSession,
    request: Request,
    *,
    reason: str,
    api_key: OrganizationApiKey | None = None,
) -> None:
    with suppress(Exception):  # pragma: no cover - best-effort audit
        await AuditService(session).record(
            action=AuditAction.API_KEY_AUTH_FAILED,
            resource_type="organization_api_key",
            resource_id=api_key.id if api_key else None,
            request=request,
            metadata={"reason": reason},
        )


async def get_current_organization_from_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(
        integration_bearer_scheme
    ),
    session: AsyncSession = Depends(get_db),
    rate_limiter: ApiKeyRateLimiter = Depends(get_api_key_rate_limiter),
) -> OrganizationApiContext:
    if credentials is None:
        _raise_401("missing bearer token")

    api_key = await OrganizationRepository(session).find_api_key_by_hash(
        hash_api_key(credentials.credentials)
    )
    if api_key is None:
        await _record_api_key_auth_failed(session, request, reason="unknown_api_key")
        _raise_401("invalid API key")

    if api_key.status is not OrganizationApiKeyStatus.ACTIVE:
        await _record_api_key_auth_failed(session, request, reason="revoked", api_key=api_key)
        _raise_401("API key is revoked")
    if api_key.expires_at is not None and _as_utc(api_key.expires_at) <= datetime.now(
        UTC
    ):
        await _record_api_key_auth_failed(session, request, reason="expired", api_key=api_key)
        _raise_401("API key has expired")

    organization = api_key.organization
    if organization is None:
        await _record_api_key_auth_failed(session, request, reason="orphaned_key", api_key=api_key)
        _raise_401("invalid API key")
    if organization.status is not OrganizationStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="organization is not active",
        )
    if organization.verification_status is OrganizationVerificationStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="organization verification was rejected",
        )

    minute = int(datetime.now(UTC).timestamp()) // 60
    if not await rate_limiter.allowed(str(api_key.id), minute):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
        )

    try:
        api_key.last_used_at = datetime.now(UTC)
        await session.commit()
    except Exception:  # pragma: no cover - best-effort last_used update
        await session.rollback()

    raw_permissions = api_key.permissions or []
    permissions = frozenset(str(p) for p in raw_permissions if isinstance(p, str))
    context = OrganizationApiContext(
        organization=organization,
        api_key=api_key,
        permissions=permissions,
    )

    request.state.organization_api_context = context
    return context


def require_api_key_permission(
    scope: OrganizationApiKeyScope,
) -> Callable[..., Coroutine[None, None, bool]]:
    async def _check_permission(
        context: OrganizationApiContext = Depends(
            get_current_organization_from_api_key
        ),
    ) -> bool:
        if scope.value not in context.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing required scope: {scope.value}",
            )
        return True

    return _check_permission


ApiKeyContext = Annotated[
    OrganizationApiContext, Depends(get_current_organization_from_api_key)
]