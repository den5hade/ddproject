from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, UploadFile, status

from app.api.v1.http_errors import raise_for
from app.dependencies.access import require_document_access, require_patient_access
from app.dependencies.auth import CurrentAccount
from app.dependencies.documents import (
    DocumentServiceDep,
    JobServiceDep,
    reject_oversized_upload,
)
from app.domain.access import AuditAction
from app.domain.medical import (
    DocumentNotFoundError,
    DocumentQuotaExceededError,
    DocumentType,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from app.schemas.document import (
    DocumentCreateRequest,
    DocumentExtractionResponse,
    DocumentResponse,
    DocumentVersionResponse,
    DownloadUrlResponse,
    JobResponse,
)
from app.services.storage import StorageUnavailableError

router = APIRouter(tags=["documents"])


@router.post(
    "/patients/{patient_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(
            require_patient_access(
                can_upload_documents=True, action=AuditAction.UPLOAD_DOCUMENT
            )
        ),
        Depends(reject_oversized_upload),
    ],
)
async def create_document(
    patient_id: UUID,
    upload: UploadFile,
    account: CurrentAccount,
    service: DocumentServiceDep,
    document_type: Annotated[DocumentType, Form()] = DocumentType.OTHER,
    title: Annotated[str, Form()] = "",
    encounter_id: Annotated[UUID | None, Form()] = None,
) -> DocumentResponse:
    payload = DocumentCreateRequest(
        document_type=document_type, title=title, encounter_id=encounter_id
    )
    try:
        document = await service.create_document(account, patient_id, payload, upload)
    except (
        DocumentNotFoundError,
        DocumentQuotaExceededError,
        FileTooLargeError,
        UnsupportedFileTypeError,
    ) as exc:
        raise_for(exc)
    return DocumentResponse.model_validate(document)


@router.get(
    "/documents/{document_id}",
    response_model=DocumentResponse,
    dependencies=[
        Depends(require_document_access(action=AuditAction.VIEW_DOCUMENT))
    ],
)
async def get_document(
    document_id: UUID,
    service: DocumentServiceDep,
) -> DocumentResponse:
    try:
        document = await service.get_document(document_id)
    except DocumentNotFoundError as exc:
        raise_for(exc)
    return DocumentResponse.model_validate(document)


@router.get(
    "/documents/{document_id}/versions",
    response_model=list[DocumentVersionResponse],
    dependencies=[
        Depends(require_document_access(action=AuditAction.VIEW_DOCUMENT))
    ],
)
async def list_versions(
    document_id: UUID,
    service: DocumentServiceDep,
) -> list[DocumentVersionResponse]:
    try:
        versions = await service.get_versions(document_id)
    except DocumentNotFoundError as exc:
        raise_for(exc)
    return [DocumentVersionResponse.model_validate(v) for v in versions]


@router.post(
    "/documents/{document_id}/versions",
    response_model=DocumentVersionResponse,
    dependencies=[
        Depends(
            require_document_access(
                flag="can_upload_documents", action=AuditAction.UPLOAD_DOCUMENT
            )
        ),
        Depends(reject_oversized_upload),
    ],
)
async def create_version(
    document_id: UUID,
    upload: UploadFile,
    account: CurrentAccount,
    service: DocumentServiceDep,
    document_type: Annotated[DocumentType, Form()] = DocumentType.OTHER,
    title: Annotated[str, Form()] = "",
    encounter_id: Annotated[UUID | None, Form()] = None,
) -> DocumentVersionResponse:
    payload = DocumentCreateRequest(
        document_type=document_type, title=title, encounter_id=encounter_id
    )
    try:
        version = await service.add_version(account, document_id, payload, upload)
    except (
        DocumentNotFoundError,
        FileTooLargeError,
        UnsupportedFileTypeError,
    ) as exc:
        raise_for(exc)
    return DocumentVersionResponse.model_validate(version)


@router.get(
    "/documents/{document_id}/extractions",
    response_model=list[DocumentExtractionResponse],
    dependencies=[
        Depends(require_document_access(action=AuditAction.VIEW_DOCUMENT))
    ],
)
async def list_extractions(
    document_id: UUID,
    service: DocumentServiceDep,
) -> list[DocumentExtractionResponse]:
    try:
        extractions = await service.get_extractions(document_id)
    except DocumentNotFoundError as exc:
        raise_for(exc)
    return [DocumentExtractionResponse.model_validate(e) for e in extractions]


@router.get(
    "/documents/{document_id}/jobs",
    response_model=list[JobResponse],
    dependencies=[
        Depends(require_document_access(action=AuditAction.VIEW_DOCUMENT))
    ],
)
async def list_jobs(
    document_id: UUID,
    service: JobServiceDep,
) -> list[JobResponse]:
    try:
        jobs = await service.list_jobs(document_id)
    except DocumentNotFoundError as exc:
        raise_for(exc)
    return [JobResponse.model_validate(j) for j in jobs]


@router.get(
    "/documents/{document_id}/download",
    response_model=DownloadUrlResponse,
    dependencies=[
        Depends(require_document_access(action=AuditAction.DOWNLOAD_DOCUMENT))
    ],
)
async def download_document(
    document_id: UUID,
    service: DocumentServiceDep,
    version_id: UUID | None = None,
) -> DownloadUrlResponse:
    try:
        url = await service.get_download_url(document_id, version_id)
    except (DocumentNotFoundError, StorageUnavailableError) as exc:
        raise_for(exc)
    return DownloadUrlResponse(download_url=url, expires_in=900)
