import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from contracts.events import OrganizationDocumentSubmitted
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import AuditAction
from app.domain.medical import (
    DocumentNotFoundError,
    DocumentType,
    PersonNotFoundError,
)
from app.domain.organization import (
    BranchStatus,
    OrganizationBranchNotFoundError,
    OrganizationDocumentIdempotencyConflictError,
)
from app.models.document import Document
from app.models.medical_record import MedicalRecord
from app.repositories.document import DocumentRepository
from app.repositories.organization import OrganizationRepository
from app.services.audit import AuditService
from app.services.documents import DocumentService
from app.services.patient_resolver import OrganizationPatientResolver

logger = logging.getLogger("account_api.organization_document")


@dataclass(frozen=True)
class OrganizationDocumentSubmitResult:
    document: Document
    patient_id: UUID
    replayed: bool


class OrganizationDocumentService:
    """Orchestrates the org integration document lifecycle (Phase 4d)."""

    def __init__(
        self, session: AsyncSession, document_service: DocumentService
    ) -> None:
        self._session = session
        self._documents = document_service
        self._document_repo = DocumentRepository(session)
        self._repos = OrganizationRepository(session)
        self._resolver = OrganizationPatientResolver(session)

    async def submit_document(
        self,
        *,
        organization_id: UUID,
        patient_email: str,
        document_type: DocumentType,
        external_id: str | None,
        branch_code: str | None,
        title: str | None,
        idempotency_key: str | None,
        upload,
        request: Request | None = None,
    ) -> OrganizationDocumentSubmitResult:
        """Create (or replay) an organization-submitted document.

        ``replayed`` marks an idempotent resubmission that did not create
        anything new (the caller then responds ``200`` instead of ``201``).
        """
        replayed = await self._existing_or_conflict(
            organization_id, external_id, idempotency_key
        )
        if replayed is not None:
            return OrganizationDocumentSubmitResult(
                document=replayed,
                patient_id=await self._patient_id_for(replayed),
                replayed=True,
            )

        branch = await self._resolve_branch(organization_id, branch_code)
        resolved = await self._resolver.resolve_by_email(patient_email)
        document = await self._documents.create_organization_document(
            organization_id=organization_id,
            organization_branch_id=branch.id if branch is not None else None,
            patient_id=resolved.patient_id,
            medical_record_id=resolved.medical_record_id,
            document_type=document_type,
            provided_document_type=document_type.value,
            external_id=external_id,
            idempotency_key=idempotency_key,
            title=title,
            upload=upload,
        )
        await AuditService(self._session).record(
            action=AuditAction.INTEGRATION_DOCUMENT_UPLOADED,
            resource_type="document",
            resource_id=document.id,
            patient_id=resolved.patient_id,
            request=request,
            metadata={
                "organization_id": str(organization_id),
                "external_id": external_id,
            },
        )
        try:
            await self._documents.publish_organization_submitted(
                OrganizationDocumentSubmitted(
                    event_id=uuid4(),
                    organization_id=organization_id,
                    document_id=document.id,
                    patient_id=resolved.patient_id,
                    external_id=external_id,
                    document_type=document_type.value,
                )
            )
        except Exception:  # pragma: no cover - best-effort side channel
            logger.exception(
                "organization_document_publish_failed document_id=%s",
                document.id,
            )
        return OrganizationDocumentSubmitResult(
            document=document,
            patient_id=resolved.patient_id,
            replayed=False,
        )

    async def get_document(
        self, organization_id: UUID, document_id: UUID
    ) -> Document:
        document = await self._document_repo.get_organization_document(
            organization_id, document_id
        )
        if document is None:
            raise DocumentNotFoundError(
                "document not found for this organization"
            )
        return document

    async def _patient_id_for(self, document: Document) -> UUID:
        record = await self._session.scalar(
            select(MedicalRecord).where(
                MedicalRecord.id == document.medical_record_id
            )
        )
        if record is None:
            raise PersonNotFoundError("document has no owning patient")
        return record.patient_id

    async def _existing_or_conflict(
        self,
        organization_id: UUID,
        external_id: str | None,
        idempotency_key: str | None,
    ) -> Document | None:
        if external_id is None and idempotency_key is None:
            return None
        by_external = None
        if external_id is not None:
            by_external = await self._document_repo.find_by_organization_external_id(
                organization_id, external_id
            )
        by_key = None
        if idempotency_key is not None:
            by_key = await self._document_repo.find_by_organization_idempotency_key(
                organization_id, idempotency_key
            )
        if (
            by_external is not None
            and by_key is not None
            and by_external.id != by_key.id
        ):
            raise OrganizationDocumentIdempotencyConflictError(
                "external_id and idempotency key refer to different documents"
            )
        return by_external if by_external is not None else by_key

    async def _resolve_branch(
        self, organization_id: UUID, branch_code: str | None
    ):
        if branch_code is None:
            return None
        branch = await self._repos.find_branch_by_code(organization_id, branch_code)
        if branch is None or branch.status is not BranchStatus.ACTIVE:
            raise OrganizationBranchNotFoundError("branch not found")
        return branch


__all__ = ["OrganizationDocumentService"]