import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import AuditAction
from app.domain.api_key import generate_raw_api_key, hash_api_key, prefix_for_raw_key
from app.domain.organization import (
    OrganizationApiKeyNotFoundError,
    OrganizationApiKeyStatus,
)
from app.models.organization import OrganizationApiKey
from app.repositories.organization import OrganizationRepository
from app.schemas.organization import ApiKeyCreate
from app.services.audit import AuditService

logger = logging.getLogger(__name__)


class OrganizationApiKeyService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repos = OrganizationRepository(session)

    async def list_api_keys(self, organization_id: UUID) -> list[OrganizationApiKey]:
        return await self._repos.list_api_keys(organization_id)

    async def get_api_key(
        self, organization_id: UUID, key_id: UUID
    ) -> OrganizationApiKey:
        key = await self._repos.get_api_key(organization_id, key_id)
        if key is None:
            raise OrganizationApiKeyNotFoundError("API key not found")
        return key

    async def find_by_hash(self, key_hash: str) -> OrganizationApiKey | None:
        return await self._repos.find_api_key_by_hash(key_hash)

    async def create_api_key(
        self,
        organization_id: UUID,
        actor_account_id: UUID,
        data: ApiKeyCreate,
        request: Request | None = None,
    ) -> tuple[OrganizationApiKey, str]:
        raw_key = generate_raw_api_key()
        key = OrganizationApiKey(
            organization_id=organization_id,
            name=data.name,
            prefix=prefix_for_raw_key(raw_key),
            key_hash=hash_api_key(raw_key),
            permissions=[scope.value for scope in data.scopes],
            status=OrganizationApiKeyStatus.ACTIVE,
            created_by_account_id=actor_account_id,
            expires_at=data.expires_at,
        )
        self._session.add(key)
        await self._session.commit()
        await AuditService(self._session).record(
            action=AuditAction.API_KEY_CREATED,
            resource_type="organization_api_key",
            resource_id=key.id,
            actor_account_id=actor_account_id,
            request=request,
        )
        logger.info(
            "api_key_created organization_id=%s account_id=%s key_id=%s",
            organization_id,
            actor_account_id,
            key.id,
        )
        return key, raw_key

    async def revoke_api_key(
        self,
        organization_id: UUID,
        key_id: UUID,
        actor_account_id: UUID,
        request: Request | None = None,
    ) -> OrganizationApiKey:
        key = await self.get_api_key(organization_id, key_id)
        if key.status == OrganizationApiKeyStatus.REVOKED:
            return key
        key.status = OrganizationApiKeyStatus.REVOKED
        key.revoked_at = datetime.now(UTC)
        await self._session.commit()
        await AuditService(self._session).record(
            action=AuditAction.API_KEY_REVOKED,
            resource_type="organization_api_key",
            resource_id=key.id,
            actor_account_id=actor_account_id,
            request=request,
        )
        logger.info(
            "api_key_revoked organization_id=%s account_id=%s key_id=%s",
            organization_id,
            actor_account_id,
            key.id,
        )
        return key

    async def rotate_api_key(
        self,
        organization_id: UUID,
        key_id: UUID,
        actor_account_id: UUID,
        request: Request | None = None,
    ) -> tuple[OrganizationApiKey, str]:
        old_key = await self.revoke_api_key(
            organization_id, key_id, actor_account_id, request
        )
        raw_key = generate_raw_api_key()
        new_key = OrganizationApiKey(
            organization_id=organization_id,
            name=old_key.name,
            prefix=prefix_for_raw_key(raw_key),
            key_hash=hash_api_key(raw_key),
            permissions=old_key.permissions,
            status=OrganizationApiKeyStatus.ACTIVE,
            created_by_account_id=actor_account_id,
            expires_at=old_key.expires_at,
        )
        self._session.add(new_key)
        await self._session.commit()
        await AuditService(self._session).record(
            action=AuditAction.API_KEY_CREATED,
            resource_type="organization_api_key",
            resource_id=new_key.id,
            actor_account_id=actor_account_id,
            request=request,
        )
        logger.info(
            "api_key_rotated organization_id=%s account_id=%s old_key_id=%s new_key_id=%s",
            organization_id,
            actor_account_id,
            old_key.id,
            new_key.id,
        )
        return new_key, raw_key