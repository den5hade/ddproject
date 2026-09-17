import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import AuditAction
from app.domain.organization import (
    OrganizationDocumentSchemaConflictError,
    OrganizationDocumentSchemaImmutableError,
    OrganizationDocumentSchemaNotFoundError,
    OrganizationDocumentSchemaStatus,
)
from app.models.organization import OrganizationDocumentSchema
from app.repositories.organization import OrganizationRepository
from app.schemas.organization import (
    OrganizationDocumentSchemaCreate,
    OrganizationDocumentSchemaUpdate,
)
from app.services.audit import AuditService

logger = logging.getLogger(__name__)


class OrganizationSchemaService:
    """CRUD + publish for org-scoped versioned document schemas (Phase 4g).

    Schemas are a **metadata registry**: ``schema_definition`` is stored as a
    JSON object and structurally validated on input, but never interpreted
    here and never coupled to the platform canonical model. Versions are
    monotonic per ``(organization_id, name)``; a DRAFT is edited freely, and
    publishing freezes it (immutable) — further changes go through a new
    version.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repos = OrganizationRepository(session)

    async def list_schemas(self, organization_id: UUID) -> list[OrganizationDocumentSchema]:
        return await self._repos.list_schemas(organization_id)

    async def get_schema(
        self, organization_id: UUID, schema_id: UUID
    ) -> OrganizationDocumentSchema:
        schema = await self._repos.get_schema(organization_id, schema_id)
        if schema is None:
            raise OrganizationDocumentSchemaNotFoundError("document schema not found")
        return schema

    async def create_schema(
        self,
        organization_id: UUID,
        actor_account_id: UUID,
        data: OrganizationDocumentSchemaCreate,
        request: Request | None = None,
    ) -> OrganizationDocumentSchema:
        existing = await self._repos.find_draft_by_name(organization_id, data.name)
        if existing is not None:
            raise OrganizationDocumentSchemaConflictError(
                f"a draft schema named '{data.name}' already exists"
            )
        version = await self._repos.find_next_version(organization_id, data.name)
        schema = OrganizationDocumentSchema(
            organization_id=organization_id,
            name=data.name,
            description=data.description,
            document_type=data.document_type,
            schema_definition=data.schema_definition,
            version=version,
            status=OrganizationDocumentSchemaStatus.DRAFT,
            created_by_account_id=actor_account_id,
        )
        self._session.add(schema)
        await self._session.commit()
        await AuditService(self._session).record(
            action=AuditAction.ORGANIZATION_SCHEMA_CREATED,
            resource_type="organization_document_schema",
            resource_id=schema.id,
            actor_account_id=actor_account_id,
            request=request,
        )
        logger.info(
            "organization_schema_created organization_id=%s schema_id=%s name=%s version=%s",
            organization_id,
            schema.id,
            schema.name,
            schema.version,
        )
        return schema

    async def update_schema(
        self,
        organization_id: UUID,
        schema_id: UUID,
        actor_account_id: UUID,
        data: OrganizationDocumentSchemaUpdate,
        request: Request | None = None,
    ) -> OrganizationDocumentSchema:
        schema = await self.get_schema(organization_id, schema_id)
        if schema.status is not OrganizationDocumentSchemaStatus.DRAFT:
            raise OrganizationDocumentSchemaImmutableError(
                "published document schemas are immutable"
            )
        changes = data.model_dump(exclude_unset=True)
        new_name = changes.get("name")
        if new_name is not None and new_name != schema.name:
            colliding = await self._repos.find_schemas_by_name(organization_id, new_name)
            if colliding:
                raise OrganizationDocumentSchemaConflictError(
                    f"a schema named '{new_name}' already exists"
                )
        for field, value in changes.items():
            setattr(schema, field, value)
        await self._session.commit()
        await AuditService(self._session).record(
            action=AuditAction.ORGANIZATION_SCHEMA_UPDATED,
            resource_type="organization_document_schema",
            resource_id=schema.id,
            actor_account_id=actor_account_id,
            request=request,
        )
        logger.info(
            "organization_schema_updated organization_id=%s schema_id=%s",
            organization_id,
            schema.id,
        )
        return schema

    async def publish_schema(
        self,
        organization_id: UUID,
        schema_id: UUID,
        actor_account_id: UUID,
        request: Request | None = None,
    ) -> OrganizationDocumentSchema:
        schema = await self.get_schema(organization_id, schema_id)
        if schema.status is not OrganizationDocumentSchemaStatus.DRAFT:
            raise OrganizationDocumentSchemaConflictError(
                "document schema is already published"
            )
        schema.status = OrganizationDocumentSchemaStatus.PUBLISHED
        schema.published_at = datetime.now(UTC)
        await self._session.commit()
        await AuditService(self._session).record(
            action=AuditAction.ORGANIZATION_SCHEMA_PUBLISHED,
            resource_type="organization_document_schema",
            resource_id=schema.id,
            actor_account_id=actor_account_id,
            request=request,
        )
        logger.info(
            "organization_schema_published organization_id=%s schema_id=%s name=%s version=%s",
            organization_id,
            schema.id,
            schema.name,
            schema.version,
        )
        return schema