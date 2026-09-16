import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from contracts.events import (
    OrganizationBatchCompleted,
    OrganizationBatchCreated,
    OrganizationDocumentSubmitted,
)
from fastapi import Request, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_factory
from app.domain.access import AuditAction
from app.domain.medical import FileTooLargeError, UnsupportedFileTypeError
from app.domain.organization import (
    BatchItemStatus,
    BatchStatus,
    BranchStatus,
    InvalidPatientIdentityError,
    OrganizationBatchNotFoundError,
    OrganizationBatchSizeLimitExceededError,
    OrganizationBranchNotFoundError,
)
from app.models.organization import (
    OrganizationUploadBatch,
    OrganizationUploadBatchItem,
)
from app.repositories.organization import OrganizationRepository
from app.schemas.integration import BulkUploadItemMetadata, BulkUploadRequest
from app.services.audit import AuditService
from app.services.documents import DocumentService
from app.services.patient_resolver import OrganizationPatientResolver

logger = logging.getLogger("account_api.organization_bulk_upload")

_MESSAGE_LIMIT = 512


@dataclass(frozen=True)
class OrganizationBulkSubmitResult:
    """Result of POST /integration/documents/bulk (§4.11)."""

    batch: OrganizationUploadBatch
    replayed: bool


class OrganizationBulkUploadService:
    """Batches org document uploads into per-item independent transactions.

    Never one giant transaction (arch §67-68): the batch header + items are
    committed first (``create_batch``), then every item is processed in its
    own fresh session (resolve patient -> create document -> mark item
    ACCEPTED + audit -> single commit). A failed item marks only itself
    REJECTED with an ``error_code``/``error_message``; the rest of the batch
    continues. ``_finalize`` rolls the counters up and emits the terminal
    ``OrganizationBatchCompleted`` event.

    Unlike the single-upload path this service commits repeatedly, by design
    (the "service commits once" convention does not hold for bulk).
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        publisher=None,
        storage=None,
        document_service_factory: Callable[[AsyncSession], DocumentService] | None = None,
    ) -> None:
        self._session = session
        self._publisher = publisher
        self._storage = storage
        self._repos = OrganizationRepository(session)
        self._document_service_factory = document_service_factory

    # -- public entry points -------------------------------------------------

    async def submit_batch(
        self,
        *,
        organization_id: UUID,
        api_key_id: UUID,
        payload: BulkUploadRequest,
        files: list[UploadFile],
        request: Request | None = None,
    ) -> OrganizationBulkSubmitResult:
        """Create + process + finalize a batch (or replay an existing one).

        ``replayed=True`` means the caller responds 200 with the untouched
        existing batch (idempotent resubmission by ``idempotency_key``).
        """
        batch, replayed = await self.create_batch(
            organization_id=organization_id,
            api_key_id=api_key_id,
            payload=payload,
            request=request,
        )
        if replayed:
            return OrganizationBulkSubmitResult(batch=batch, replayed=True)
        await self._process_items(
            organization_id=organization_id,
            batch_id=batch.id,
            items=payload.items,
            files=files,
            request=request,
        )
        await self._finalize(batch_id=batch.id, request=request)
        batch = await self.get_batch(organization_id, batch.id)
        return OrganizationBulkSubmitResult(batch=batch, replayed=False)

    async def create_batch(
        self,
        *,
        organization_id: UUID,
        api_key_id: UUID,
        payload: BulkUploadRequest,
        request: Request | None = None,
    ) -> tuple[OrganizationUploadBatch, bool]:
        """Persist the batch + items, or return an existing batch by key."""
        if len(payload.items) > settings.integration_max_batch_size:
            raise OrganizationBatchSizeLimitExceededError(
                f"batch exceeds the maximum of {settings.integration_max_batch_size} items"
            )
        if payload.idempotency_key is not None:
            existing = await self._repos.find_batch_by_idempotency_key(
                organization_id, payload.idempotency_key
            )
            if existing is not None:
                return existing, True

        batch = OrganizationUploadBatch(
            organization_id=organization_id,
            api_key_id=api_key_id,
            idempotency_key=payload.idempotency_key,
            status=BatchStatus.ACCEPTED,
            total_count=len(payload.items),
        )
        self._session.add(batch)
        await self._session.flush()
        for index, item in enumerate(payload.items):
            self._session.add(
                OrganizationUploadBatchItem(
                    batch_id=batch.id,
                    item_index=index,
                    patient_email=item.patient_email,
                    document_type=item.document_type,
                    external_id=item.external_id,
                    branch_code=item.branch_code,
                    title=item.title,
                    status=BatchItemStatus.PENDING,
                )
            )
        await self._session.commit()
        await AuditService(self._session).record(
            action=AuditAction.INTEGRATION_BATCH_CREATED,
            resource_type="batch",
            resource_id=batch.id,
            request=request,
            metadata={
                "organization_id": str(organization_id),
                "total": len(payload.items),
            },
        )
        await self._publish(
            "organization.batch.created",
            OrganizationBatchCreated(
                event_id=uuid4(),
                organization_id=organization_id,
                batch_id=batch.id,
                total_count=len(payload.items),
            ),
        )
        return batch, False

    async def get_batch(
        self, organization_id: UUID, batch_id: UUID
    ) -> OrganizationUploadBatch:
        """Org-scoped batch read (foreign/missing -> 404; no IDOR)."""
        batch = await self._repos.get_batch(organization_id, batch_id)
        if batch is None:
            raise OrganizationBatchNotFoundError("batch not found")
        return batch

    async def get_batch_items(
        self, organization_id: UUID, batch_id: UUID
    ) -> list[OrganizationUploadBatchItem]:
        """Org-scoped batch items (gate on the batch itself for 404 isolation)."""
        await self.get_batch(organization_id, batch_id)
        return await OrganizationRepository(self._session).list_batch_items(batch_id)

    # -- internals -----------------------------------------------------------

    def _document_service(self, session: AsyncSession) -> DocumentService:
        if self._document_service_factory is not None:
            return self._document_service_factory(session)
        return DocumentService(
            session=session,
            publisher=self._publisher,
            storage=self._storage,
        )

    def _session_factory(self, request: Request | None):
        if request is not None:
            try:
                factory = getattr(request.app.state, "api_request_db_factory", None)
                if factory is not None:
                    return factory
            except Exception:  # pragma: no cover - scope without an app root
                pass
        return async_session_factory

    async def _process_items(
        self,
        *,
        organization_id: UUID,
        batch_id: UUID,
        items: list[BulkUploadItemMetadata],
        files: list[UploadFile],
        request: Request | None,
    ) -> None:
        for index, meta in enumerate(items):
            upload = files[index] if index < len(files) else None
            await self._process_item(
                organization_id=organization_id,
                batch_id=batch_id,
                item_index=index,
                meta=meta,
                upload=upload,
                request=request,
            )

    async def _process_item(
        self,
        *,
        organization_id: UUID,
        batch_id: UUID,
        item_index: int,
        meta: BulkUploadItemMetadata,
        upload: UploadFile | None,
        request: Request | None,
    ) -> None:
        factory = self._session_factory(request)
        try:
            async with factory() as session:
                if upload is None:
                    raise ValueError("missing uploaded file for item")
                branch = await self._resolve_branch(
                    session, organization_id, meta.branch_code
                )
                resolved = await OrganizationPatientResolver(
                    session
                ).resolve_by_email(meta.patient_email)
                documents = self._document_service(session)
                document = await documents.create_organization_document(
                    organization_id=organization_id,
                    organization_branch_id=branch.id if branch is not None else None,
                    patient_id=resolved.patient_id,
                    medical_record_id=resolved.medical_record_id,
                    document_type=meta.document_type,
                    provided_document_type=meta.document_type.value,
                    external_id=meta.external_id,
                    idempotency_key=None,
                    title=meta.title,
                    upload=upload,
                )
                item = await self._get_item(session, batch_id, item_index)
                item.status = BatchItemStatus.ACCEPTED
                item.document_id = document.id
                item.error_code = None
                item.error_message = None
                await AuditService(session).record(
                    action=AuditAction.INTEGRATION_DOCUMENT_UPLOADED,
                    resource_type="document",
                    resource_id=document.id,
                    patient_id=resolved.patient_id,
                    request=request,
                    metadata={
                        "organization_id": str(organization_id),
                        "external_id": meta.external_id,
                    },
                )
            await self._publish(
                "organization.document.submitted",
                OrganizationDocumentSubmitted(
                    event_id=uuid4(),
                    organization_id=organization_id,
                    document_id=document.id,
                    patient_id=resolved.patient_id,
                    external_id=meta.external_id,
                    document_type=meta.document_type.value,
                ),
            )
        except Exception as exc:
            logger.warning(
                "batch_item_rejected batch_id=%s item_index=%s error=%s",
                batch_id,
                item_index,
                exc,
            )
            await self._reject_item(
                batch_id=batch_id,
                item_index=item_index,
                error_code=self._error_code_for(exc),
                error_message=str(exc)[:_MESSAGE_LIMIT],
                request=request,
            )

    async def _reject_item(
        self,
        *,
        batch_id: UUID,
        item_index: int,
        error_code: str,
        error_message: str,
        request: Request | None,
    ) -> None:
        factory = self._session_factory(request)
        async with factory() as session:
            item = await self._get_item(session, batch_id, item_index)
            if item is None:
                return
            item.status = BatchItemStatus.REJECTED
            item.error_code = error_code
            item.error_message = error_message
            await session.commit()

    async def _finalize(self, *, batch_id: UUID, request: Request | None) -> None:
        factory = self._session_factory(request)
        async with factory() as session:
            batch = await session.get(OrganizationUploadBatch, batch_id)
            if batch is None:
                return
            items = await OrganizationRepository(session).list_batch_items(batch_id)
            accepted = sum(
                1 for item in items if item.status is BatchItemStatus.ACCEPTED
            )
            failed = sum(1 for item in items if item.status is BatchItemStatus.REJECTED)
            batch.accepted_count = accepted
            batch.failed_count = failed
            batch.completed_at = datetime.now(UTC)
            if failed == 0:
                batch.status = BatchStatus.COMPLETED
            elif accepted == 0:
                batch.status = BatchStatus.FAILED
            else:
                batch.status = BatchStatus.PARTIAL
            await session.commit()
        await self._publish(
            "organization.batch.completed",
            OrganizationBatchCompleted(
                event_id=uuid4(),
                organization_id=batch.organization_id,
                batch_id=batch.id,
                status=batch.status.value,
                total_count=batch.total_count,
                accepted_count=batch.accepted_count,
                failed_count=batch.failed_count,
            ),
        )

    async def _get_item(
        self, session: AsyncSession, batch_id: UUID, item_index: int
    ) -> OrganizationUploadBatchItem | None:
        result = await session.execute(
            select(OrganizationUploadBatchItem).where(
                OrganizationUploadBatchItem.batch_id == batch_id,
                OrganizationUploadBatchItem.item_index == item_index,
            )
        )
        return result.scalar_one_or_none()

    async def _resolve_branch(
        self, session: AsyncSession, organization_id: UUID, branch_code: str | None
    ):
        if branch_code is None:
            return None
        branch = await OrganizationRepository(session).find_branch_by_code(
            organization_id, branch_code
        )
        if branch is None or branch.status is not BranchStatus.ACTIVE:
            raise OrganizationBranchNotFoundError("branch not found")
        return branch

    async def _publish(self, routing_key: str, event) -> None:
        if self._publisher is None:
            logger.warning(
                "event_dropped routing_key=%s (broker unavailable)", routing_key
            )
            return
        try:
            await self._publisher.publish(routing_key, event)
        except Exception:  # pragma: no cover - best-effort side channel
            logger.exception("batch_event_publish_failed routing_key=%s", routing_key)

    @staticmethod
    def _error_code_for(exc: Exception) -> str:
        if isinstance(exc, IntegrityError):
            return "duplicate_external_id"
        if isinstance(exc, InvalidPatientIdentityError):
            return "patient_resolution_failed"
        if isinstance(exc, OrganizationBranchNotFoundError):
            return "branch_not_found"
        if isinstance(exc, FileTooLargeError):
            return "file_too_large"
        if isinstance(exc, UnsupportedFileTypeError):
            return "unsupported_file_type"
        return "internal_error"


__all__ = ["OrganizationBulkSubmitResult", "OrganizationBulkUploadService"]