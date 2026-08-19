import logging
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

from contracts.events import (
    DocumentAnalysisCompleted,
    DocumentConverted,
    DocumentProcessingFailed,
    DocumentStored,
    DocumentUploaded,
    DocumentUploadRequested,
)
from fastapi import UploadFile
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from storage import ALLOWED_MIME_TYPES

from app.core.config import settings
from app.domain.access import GrantStatus
from app.domain.medical import (
    DocumentAccessDeniedError,
    DocumentNotFoundError,
    DocumentQuotaExceededError,
    DocumentStatus,
    ExtractionStatus,
    FileTooLargeError,
    ProcessingJobStatus,
    ProcessingJobType,
    UnsupportedFileTypeError,
)
from app.models.access_grant import PatientAccessGrant
from app.models.account import Account
from app.models.document import Document, DocumentVersion
from app.models.extraction import DocumentExtraction
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.processing_job import DocumentProcessingJob
from app.repositories.document import (
    DocumentRepository,
    DocumentVersionRepository,
    ExtractionRepository,
    ProcessingJobRepository,
)
from app.repositories.patient import PatientRepository
from app.schemas.document import DocumentCreateRequest
from app.services.storage import StorageService

logger = logging.getLogger("account_api.documents")

FREE_DOCUMENT_LIMIT = 10
_CHUNK = 1024 * 1024

_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        logger.warning("staged_file_cleanup_failed path=%s", path)


class DocumentService:
    """Document/version persistence, quota, access checks and pipeline events."""

    def __init__(
        self,
        session: AsyncSession,
        publisher=None,
        storage: StorageService | None = None,
    ) -> None:
        self._session = session
        self._publisher = publisher
        self._storage = storage or StorageService.from_settings()
        self._documents = DocumentRepository(session)
        self._versions = DocumentVersionRepository(session)
        self._jobs = ProcessingJobRepository(session)
        self._extractions = ExtractionRepository(session)
        self._patients = PatientRepository(session)

    # ------------------------------------------------------------------ upload
    async def create_document(
        self,
        account: Account,
        patient_id: UUID,
        data: DocumentCreateRequest,
        upload: UploadFile,
    ) -> Document:
        patient, medical_record = await self._patient_and_record(patient_id)
        if not await self._can_upload(account, patient):
            raise DocumentAccessDeniedError("no permission to upload documents for this patient")
        if (
            not account.is_subscribed
            and await self._documents.count_owned(medical_record.id) >= FREE_DOCUMENT_LIMIT
        ):
            raise DocumentQuotaExceededError(
                f"free plan allows at most {FREE_DOCUMENT_LIMIT} documents"
            )
        filename = os.path.basename(upload.filename or "")
        if not filename:
            raise UnsupportedFileTypeError("missing original filename")
        mime = self._detect_mime(upload.content_type, filename)
        temp_path, size = await self._stage_upload(upload)

        try:
            document = await self._documents.create(
                medical_record_id=medical_record.id,
                encounter_id=data.encounter_id,
                document_type=data.document_type,
                title=data.title or os.path.splitext(filename)[0],
                original_filename=filename,
                mime_type=mime,
                size_bytes=size,
                storage_key="",
                status=DocumentStatus.PENDING,
                uploaded_by_account_id=account.id,
            )
            version = await self._versions.create(
                document_id=document.id,
                version=1,
                s3_key="",
                mime_type=mime,
                size_bytes=size,
                created_by_account_id=account.id,
            )
            await self._jobs.create(
                document_id=document.id,
                document_version_id=version.id,
                job_type=ProcessingJobType.PDF_CONVERSION,
            )
            published = await self._publish(
                "document.upload.requested",
                DocumentUploadRequested(
                    event_id=uuid4(),
                    document_id=document.id,
                    document_version_id=version.id,
                    patient_id=patient.id,
                    tenant_id=self._storage.tenant_id(),
                    medical_record_id=medical_record.id,
                    temp_path=temp_path,
                    original_filename=filename,
                    mime_type=mime,
                    size_bytes=size,
                ),
            )
            if not published:
                _safe_remove(temp_path)
            await self._session.commit()
        except Exception:
            _safe_remove(temp_path)
            raise
        logger.info(
            "document_created document_id=%s patient_id=%s size=%s",
            document.id,
            patient.id,
            size,
        )
        return document

    async def add_version(
        self,
        account: Account,
        document_id: UUID,
        data: DocumentCreateRequest,
        upload: UploadFile,
    ) -> DocumentVersion:
        document = await self.get_document(account, document_id)
        patient = await self._document_patient(document)
        if patient is None or not await self._can_upload(account, patient):
            raise DocumentAccessDeniedError("no permission to upload documents for this patient")
        filename = os.path.basename(upload.filename or "")
        if not filename:
            raise UnsupportedFileTypeError("missing original filename")
        mime = self._detect_mime(upload.content_type, filename)
        temp_path, size = await self._stage_upload(upload)

        try:
            latest = await self._versions.latest(document_id)
            next_version = latest.version + 1 if latest else 1
            version = await self._versions.create(
                document_id=document_id,
                version=next_version,
                s3_key="",
                mime_type=mime,
                size_bytes=size,
                created_by_account_id=account.id,
            )
            await self._jobs.create(
                document_id=document_id,
                document_version_id=version.id,
                job_type=ProcessingJobType.PDF_CONVERSION,
            )
            document.status = DocumentStatus.PENDING
            published = await self._publish(
                "document.upload.requested",
                DocumentUploadRequested(
                    event_id=uuid4(),
                    document_id=document_id,
                    document_version_id=version.id,
                    patient_id=patient.id,
                    tenant_id=self._storage.tenant_id(),
                    medical_record_id=document.medical_record_id,
                    temp_path=temp_path,
                    original_filename=filename,
                    mime_type=mime,
                    size_bytes=size,
                ),
            )
            if not published:
                _safe_remove(temp_path)
            await self._session.commit()
        except Exception:
            _safe_remove(temp_path)
            raise
        logger.info("document_version_created document_id=%s version=%s", document_id, next_version)
        return version

    # ------------------------------------------------------------------- reads
    async def get_document(self, account: Account, document_id: UUID) -> Document:
        document = await self._documents.get(document_id)
        if document is None:
            raise DocumentNotFoundError("document not found")
        patient = await self._document_patient(document)
        if patient is None or not await self._can_view(account, patient):
            raise DocumentAccessDeniedError("no access to this document")
        return document

    async def list_documents(self, account: Account, patient_id: UUID) -> list[Document]:
        patient, medical_record = await self._patient_and_record(patient_id)
        if not await self._can_view(account, patient):
            raise DocumentAccessDeniedError("no access to this patient's documents")
        return await self._documents.list_by_medical_record(medical_record.id)

    async def get_versions(
        self, account: Account, document_id: UUID
    ) -> list[DocumentVersion]:
        document = await self.get_document(account, document_id)
        return await self._versions.list_by_document(document.id)

    async def get_extractions(
        self, account: Account, document_id: UUID
    ) -> list[DocumentExtraction]:
        document = await self.get_document(account, document_id)
        return await self._extractions.list_by_document(document.id)

    async def get_download_url(
        self,
        account: Account,
        document_id: UUID,
        version_id: UUID | None = None,
    ) -> str:
        document = await self.get_document(account, document_id)
        version = (
            await self._versions.get(version_id)
            if version_id is not None
            else await self._versions.latest(document.id)
        )
        if version is None or not version.s3_key:
            raise DocumentNotFoundError("no stored version available yet")
        return self._storage.download_url(version.s3_key, filename=document.original_filename)

    # ----------------------------------------------------- pipeline event sinks
    async def on_document_stored(self, event: DocumentStored) -> None:
        version = await self._version_or_skip(event)
        if version is None:
            return
        first_store = version.checksum is None
        version.s3_key = event.storage_key
        version.mime_type = event.mime_type
        version.size_bytes = event.size_bytes
        version.checksum = event.checksum

        document = await self._documents.get(event.document_id)
        if document is not None:
            document.storage_key = event.storage_key
            document.mime_type = event.mime_type
            document.size_bytes = event.size_bytes
            document.status = DocumentStatus.PROCESSING

        if first_store:
            await self._publish(
                "document.uploaded",
                DocumentUploaded(
                    event_id=uuid4(),
                    document_id=event.document_id,
                    document_version_id=event.document_version_id,
                    patient_id=event.patient_id,
                    storage_key=event.storage_key,
                ),
            )
        await self._session.commit()
        logger.info("document_stored document_id=%s version_id=%s", event.document_id, version.id)

    async def on_document_converted(self, event: DocumentConverted) -> None:
        job = await self._conversion_job_or_skip(event)
        if job is None:
            return
        job.status = ProcessingJobStatus.SUCCEEDED
        job.finished_at = _now()
        await self._session.commit()
        logger.info(
            "document_converted document_id=%s version_id=%s",
            event.document_id,
            event.document_version_id,
        )

    async def on_document_analysis_completed(
        self, event: DocumentAnalysisCompleted
    ) -> None:
        extraction = await self._extractions.get(event.extraction_id)
        if extraction is None:
            extraction = DocumentExtraction(
                id=event.extraction_id,
                document_id=event.document_id,
                document_version_id=event.document_version_id,
                schema_name=event.schema_name,
                schema_version=event.schema_version,
            )
            await self._extractions.save(extraction)

        succeeded = event.status == "succeeded"
        extraction.status = ExtractionStatus.SUCCEEDED if succeeded else ExtractionStatus.FAILED
        extraction.confidence = event.confidence
        extraction.data = event.data

        document = await self._documents.get(event.document_id)
        if document is not None:
            document.status = DocumentStatus.COMPLETED if succeeded else DocumentStatus.FAILED
        await self._session.commit()
        logger.info(
            "document_analysis document_id=%s extraction_id=%s status=%s",
            event.document_id,
            event.extraction_id,
            event.status,
        )

    async def on_document_processing_failed(
        self, event: DocumentProcessingFailed
    ) -> None:
        document = await self._documents.get(event.document_id)
        if document is not None:
            document.status = DocumentStatus.FAILED
        job = await self._conversion_job_or_skip(event)
        if job is not None:
            job.status = ProcessingJobStatus.FAILED
            job.error_code = event.error_code
            job.error_message = event.error_message
            job.finished_at = _now()
        await self._session.commit()
        logger.info(
            "document_failed document_id=%s code=%s",
            event.document_id,
            event.error_code,
        )

    # ---------------------------------------------------------------- helpers
    async def _conversion_job_or_skip(
        self, event
    ) -> DocumentProcessingJob | None:
        if event.document_version_id is None:
            return None
        job = await self._jobs.get_by_version(event.document_version_id)
        if job is None:
            logger.warning(
                "event_unknown_version event=%s version_id=%s",
                type(event).__name__,
                event.document_version_id,
            )
            return None
        return job

    async def _version_or_skip(self, event) -> DocumentVersion | None:
        if event.document_version_id is None:
            return None
        version = await self._versions.get(event.document_version_id)
        if version is None:
            logger.warning(
                "event_unknown_version event=%s version_id=%s",
                type(event).__name__,
                event.document_version_id,
            )
            return None
        return version

    async def _publish(self, routing_key: str, event) -> bool:
        if self._publisher is None:
            logger.warning(
                "event_dropped routing_key=%s document_id=%s (broker unavailable)",
                routing_key,
                event.document_id,
            )
            return False
        await self._publisher.publish(routing_key, event)
        return True

    async def _stage_upload(self, upload: UploadFile) -> tuple[str, int]:
        os.makedirs(settings.storage_temp_dir, exist_ok=True)
        temp_path = os.path.join(settings.storage_temp_dir, f"{uuid4().hex}.upload")
        size = 0
        try:
            with open(temp_path, "wb") as out:
                while chunk := await upload.read(_CHUNK):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise FileTooLargeError(
                            f"file exceeds the maximum of {settings.max_upload_bytes} bytes"
                        )
                    out.write(chunk)
        except Exception:
            _safe_remove(temp_path)
            raise
        return temp_path, size

    @staticmethod
    def _detect_mime(content_type: str | None, filename: str) -> str:
        if content_type and content_type.lower() in ALLOWED_MIME_TYPES:
            return content_type.lower()
        extension = os.path.splitext(filename)[1].lower()
        mime = _MIME_BY_EXT.get(extension)
        if mime is None:
            raise UnsupportedFileTypeError(f"unsupported file type: {filename}")
        return mime

    async def _patient_and_record(self, patient_id: UUID) -> tuple[Patient, MedicalRecord]:
        patient = await self._patients.get_by_id(patient_id)
        if patient is None:
            raise DocumentNotFoundError("patient not found")
        medical_record = await self._session.scalar(
            select(MedicalRecord).where(MedicalRecord.patient_id == patient_id)
        )
        if medical_record is None:
            raise DocumentNotFoundError("patient has no medical record")
        return patient, medical_record

    async def _document_patient(self, document: Document) -> Patient | None:
        medical_record = await self._session.get(
            MedicalRecord, document.medical_record_id
        )
        if medical_record is None:
            return None
        return await self._patients.get_by_id(medical_record.patient_id)

    async def _can_upload(self, account: Account, patient: Patient) -> bool:
        if account.person_id == patient.person_id:
            return True
        return await self._has_active_grant(account.id, patient.id, "can_upload_documents")

    async def _can_view(self, account: Account, patient: Patient) -> bool:
        if account.person_id == patient.person_id:
            return True
        return await self._has_active_grant(account.id, patient.id, "can_view_documents")

    async def _has_active_grant(
        self, account_id: UUID, patient_id: UUID, flag: str
    ) -> bool:
        now = datetime.now(UTC)
        result = await self._session.scalar(
            select(PatientAccessGrant.id)
            .where(
                PatientAccessGrant.patient_id == patient_id,
                PatientAccessGrant.account_id == account_id,
                PatientAccessGrant.status == GrantStatus.ACTIVE,
                getattr(PatientAccessGrant, flag).is_(True),
                or_(
                    PatientAccessGrant.expires_at.is_(None),
                    PatientAccessGrant.expires_at > now,
                ),
            )
            .limit(1)
        )
        return result is not None


__all__ = ["DocumentService", "FREE_DOCUMENT_LIMIT"]