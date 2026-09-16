import json
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.v1.http_errors import raise_for
from app.dependencies.documents import reject_oversized_upload
from app.dependencies.integration import (
    ApiKeyContext,
    OrganizationBulkUploadServiceDep,
    OrganizationDocumentServiceDep,
    require_api_key_permission,
)
from app.domain.medical import (
    DocumentNotFoundError,
    DocumentType,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from app.domain.organization import (
    InvalidPatientIdentityError,
    OrganizationApiKeyScope,
    OrganizationBatchNotFoundError,
    OrganizationBatchSizeLimitExceededError,
    OrganizationBranchNotFoundError,
    OrganizationDocumentIdempotencyConflictError,
)
from app.schemas.integration import (
    BulkUploadRequest as BulkUploadInput,
)
from app.schemas.integration import (
    BulkUploadResponse,
    IntegrationDocumentResponse,
    IntegrationDocumentStatusResponse,
    OrganizationBatchItemResponse,
    OrganizationBatchResponse,
)
from app.schemas.integration import IntegrationDocumentSubmit as IntegrationDocumentInput

router = APIRouter(prefix="/integration", tags=["integration"])

RequireUploadScope = Annotated[
    bool, Depends(require_api_key_permission(OrganizationApiKeyScope.DOCUMENTS_UPLOAD))
]
RequireBulkUploadScope = Annotated[
    bool,
    Depends(require_api_key_permission(OrganizationApiKeyScope.DOCUMENTS_BULK_UPLOAD)),
]
RequireReadScope = Annotated[
    bool, Depends(require_api_key_permission(OrganizationApiKeyScope.DOCUMENTS_READ))
]


@router.post(
    "/documents",
    response_model=IntegrationDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(reject_oversized_upload)],
    summary="Submit a document",
)
async def submit_document(
    patient_email: Annotated[str, Form()],
    upload: UploadFile,
    _permission: RequireUploadScope,
    context: ApiKeyContext,
    service: OrganizationDocumentServiceDep,
    request: Request,
    response: Response,
    document_type: Annotated[DocumentType | None, Form()] = None,
    external_id: Annotated[str | None, Form()] = None,
    branch_code: Annotated[str | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> IntegrationDocumentResponse:
    """Accept an organization document submission (Phase 4d).

    Returns ``201`` for a new submission and ``200`` for an idempotent replay
    keyed by ``external_id`` or the ``Idempotency-Key`` header.
    """
    try:
        payload = IntegrationDocumentInput.model_validate(
            {
                "patient_email": patient_email,
                **({"document_type": document_type} if document_type is not None else {}),
                **({"external_id": external_id} if external_id is not None else {}),
                **({"branch_code": branch_code} if branch_code is not None else {}),
                **({"title": title} if title is not None else {}),
            }
        )
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    try:
        submit_result = await service.submit_document(
            organization_id=context.organization_id,
            patient_email=payload.patient_email,
            document_type=payload.document_type,
            external_id=payload.external_id,
            branch_code=payload.branch_code,
            title=payload.title,
            idempotency_key=idempotency_key,
            upload=upload,
            request=request,
        )
    except (
        InvalidPatientIdentityError,
        OrganizationBranchNotFoundError,
        OrganizationDocumentIdempotencyConflictError,
        FileTooLargeError,
        UnsupportedFileTypeError,
    ) as exc:
        raise_for(exc)
    if submit_result.replayed:
        response.status_code = status.HTTP_200_OK
    return IntegrationDocumentResponse(
        document_id=submit_result.document.id,
        status="processing",
        external_id=submit_result.document.external_id,
        patient_id=submit_result.patient_id,
    )


@router.get(
    "/documents/{document_id}",
    response_model=IntegrationDocumentStatusResponse,
    summary="Get an organization document status",
)
async def get_document(
    document_id: UUID,
    _permission: RequireReadScope,
    context: ApiKeyContext,
    service: OrganizationDocumentServiceDep,
) -> IntegrationDocumentStatusResponse:
    """Return the current state of an org-submitted document (org-scoped)."""
    try:
        document = await service.get_document(context.organization_id, document_id)
    except DocumentNotFoundError as exc:
        raise_for(exc)
    return IntegrationDocumentStatusResponse(
        document_id=document.id,
        status=document.status,
        document_type=document.document_type,
        external_id=document.external_id,
        organization_id=document.organization_id,
        document_date=document.document_date,
        created_at=document.created_at,
    )


@router.post(
    "/documents/bulk",
    response_model=BulkUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(reject_oversized_upload)],
    summary="Submit a batch of documents",
)
async def submit_bulk(
    metadata: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
    _permission: RequireBulkUploadScope,
    context: ApiKeyContext,
    service: OrganizationBulkUploadServiceDep,
    request: Request,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> BulkUploadResponse:
    """Accept an organization bulk submission (Phase 4e, §4.11).

    ``metadata`` is a JSON array describing one item per uploaded file (same
    index); each item is processed in its own transaction, so partial failures
    are tracked per item. Returns ``202`` for a new batch and ``200`` for an
    idempotent replay by the ``Idempotency-Key`` header.
    """
    try:
        raw_items = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise RequestValidationError(
            [
                {
                    "loc": ("body", "metadata"),
                    "msg": "metadata must be a JSON array of item objects",
                    "type": "json_invalid",
                }
            ]
        ) from exc
    try:
        payload = BulkUploadInput.model_validate(
            {"items": raw_items, "idempotency_key": idempotency_key}
        )
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    if len(files) != len(payload.items):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="the number of uploaded files must match the metadata items",
        )
    try:
        result = await service.submit_batch(
            organization_id=context.organization_id,
            api_key_id=context.api_key_id,
            payload=payload,
            files=files,
            request=request,
        )
    except OrganizationBatchSizeLimitExceededError as exc:
        raise_for(exc)
    if result.replayed:
        response.status_code = status.HTTP_200_OK
    batch = result.batch
    return BulkUploadResponse(
        batch_id=batch.id,
        status=batch.status,
        total_count=batch.total_count,
        accepted_count=batch.accepted_count,
        failed_count=batch.failed_count,
        idempotency_key=batch.idempotency_key,
    )


@router.get(
    "/batches/{batch_id}",
    response_model=OrganizationBatchResponse,
    summary="Get an upload batch",
)
async def get_batch(
    batch_id: UUID,
    _permission: RequireReadScope,
    context: ApiKeyContext,
    service: OrganizationBulkUploadServiceDep,
) -> OrganizationBatchResponse:
    """Return an org upload batch with its items (org-scoped, no IDOR)."""
    try:
        batch = await service.get_batch(context.organization_id, batch_id)
    except OrganizationBatchNotFoundError as exc:
        raise_for(exc)
    return OrganizationBatchResponse.model_validate(batch)


@router.get(
    "/batches/{batch_id}/items",
    response_model=list[OrganizationBatchItemResponse],
    summary="List an upload batch's items",
)
async def get_batch_items(
    batch_id: UUID,
    _permission: RequireReadScope,
    context: ApiKeyContext,
    service: OrganizationBulkUploadServiceDep,
) -> list[OrganizationBatchItemResponse]:
    """Return the items of an org upload batch (org-scoped, no IDOR)."""
    try:
        items = await service.get_batch_items(context.organization_id, batch_id)
    except OrganizationBatchNotFoundError as exc:
        raise_for(exc)
    return [OrganizationBatchItemResponse.model_validate(item) for item in items]