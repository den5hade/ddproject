from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Form,
    Header,
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
    OrganizationBranchNotFoundError,
    OrganizationDocumentIdempotencyConflictError,
)
from app.schemas.integration import (
    IntegrationDocumentResponse,
    IntegrationDocumentStatusResponse,
)
from app.schemas.integration import IntegrationDocumentSubmit as IntegrationDocumentInput

router = APIRouter(prefix="/integration", tags=["integration"])

RequireUploadScope = Annotated[
    bool, Depends(require_api_key_permission(OrganizationApiKeyScope.DOCUMENTS_UPLOAD))
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