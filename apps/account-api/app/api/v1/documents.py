from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status

from app.dependencies.access import require_document_access, require_patient_access
from app.dependencies.auth import CurrentAccount
from app.dependencies.documents import DocumentServiceDep, JobServiceDep
from app.domain.access import AuditAction
from app.domain.medical import (
    DocumentNotFoundError,
    DocumentQuotaExceededError,
    DocumentType,
    FileTooLargeError,
    JobNotFoundError,
    UnsupportedFileTypeError,
)
from app.models.document import Document, DocumentVersion
from app.models.extraction import DocumentExtraction
from app.models.processing_job import DocumentProcessingJob
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


def _document_response(document: Document) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        medical_record_id=document.medical_record_id,
        encounter_id=document.encounter_id,
        document_type=document.document_type,
        title=document.title,
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        storage_key=document.storage_key,
        status=document.status,
        uploaded_by_account_id=document.uploaded_by_account_id,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _version_response(version: DocumentVersion) -> DocumentVersionResponse:
    return DocumentVersionResponse(
        id=version.id,
        document_id=version.document_id,
        version=version.version,
        s3_key=version.s3_key,
        mime_type=version.mime_type,
        size_bytes=version.size_bytes,
        checksum=version.checksum,
        created_by_account_id=version.created_by_account_id,
        created_at=version.created_at,
    )


def _extraction_response(extraction: DocumentExtraction) -> DocumentExtractionResponse:
    return DocumentExtractionResponse(
        id=extraction.id,
        document_id=extraction.document_id,
        document_version_id=extraction.document_version_id,
        schema_name=extraction.schema_name,
        schema_version=extraction.schema_version,
        status=extraction.status,
        confidence=extraction.confidence,
        data=extraction.data,
        created_at=extraction.created_at,
        updated_at=extraction.updated_at,
    )


def _job_response(job: DocumentProcessingJob) -> JobResponse:
    return JobResponse(
        id=job.id,
        document_id=job.document_id,
        document_version_id=job.document_version_id,
        job_type=job.job_type,
        status=job.status,
        attempts=job.attempts,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_code=job.error_code,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _http_error(exc: Exception) -> HTTPException:
    codes = {
        DocumentNotFoundError: status.HTTP_404_NOT_FOUND,
        JobNotFoundError: status.HTTP_404_NOT_FOUND,
        DocumentQuotaExceededError: status.HTTP_429_TOO_MANY_REQUESTS,
        FileTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
        UnsupportedFileTypeError: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        StorageUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
    }
    return HTTPException(
        status_code=codes.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


@router.post(
    "/patients/{patient_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(
            require_patient_access(
                can_upload_documents=True, action=AuditAction.UPLOAD_DOCUMENT
            )
        )
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
        raise _http_error(exc) from exc
    return _document_response(document)


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
        raise _http_error(exc) from exc
    return _document_response(document)


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
        raise _http_error(exc) from exc
    return [_version_response(version) for version in versions]


@router.post(
    "/documents/{document_id}/versions",
    response_model=DocumentVersionResponse,
    dependencies=[
        Depends(
            require_document_access(
                flag="can_upload_documents", action=AuditAction.UPLOAD_DOCUMENT
            )
        )
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
        raise _http_error(exc) from exc
    return _version_response(version)


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
        raise _http_error(exc) from exc
    return [_extraction_response(extraction) for extraction in extractions]


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
        raise _http_error(exc) from exc
    return [_job_response(job) for job in jobs]


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
        raise _http_error(exc) from exc
    return DownloadUrlResponse(download_url=url, expires_in=900)