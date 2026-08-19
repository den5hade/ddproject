from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.medical import DocumentStatus, DocumentType, ProcessingJobType
from app.models.document import Document, DocumentVersion
from app.models.extraction import DocumentExtraction
from app.models.processing_job import DocumentProcessingJob


class DocumentRepository:
    """SQL access for ``documents``; never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        medical_record_id: UUID,
        encounter_id: UUID | None,
        document_type: DocumentType,
        title: str,
        original_filename: str,
        mime_type: str,
        size_bytes: int,
        storage_key: str,
        status: DocumentStatus,
        uploaded_by_account_id: UUID | None,
    ) -> Document:
        document = Document(
            medical_record_id=medical_record_id,
            encounter_id=encounter_id,
            document_type=document_type,
            title=title,
            original_filename=original_filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            storage_key=storage_key,
            status=status,
            uploaded_by_account_id=uploaded_by_account_id,
        )
        self._session.add(document)
        await self._session.flush()
        return document

    async def get(self, document_id: UUID) -> Document | None:
        return await self._session.get(Document, document_id)

    async def list_by_medical_record(self, medical_record_id: UUID) -> list[Document]:
        result = await self._session.execute(
            select(Document)
            .where(Document.medical_record_id == medical_record_id)
            .order_by(Document.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_encounter(self, encounter_id: UUID) -> list[Document]:
        result = await self._session.execute(
            select(Document)
            .where(Document.encounter_id == encounter_id)
            .order_by(Document.created_at.desc())
        )
        return list(result.scalars().all())

    async def count_owned(self, medical_record_id: UUID) -> int:
        result = await self._session.execute(
            select(Document.id).where(Document.medical_record_id == medical_record_id)
        )
        return len(result.scalars().all())


class DocumentVersionRepository:
    """SQL access for ``document_versions``; never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        document_id: UUID,
        version: int,
        s3_key: str = "",
        mime_type: str = "",
        size_bytes: int = 0,
        created_by_account_id: UUID | None = None,
    ) -> DocumentVersion:
        row = DocumentVersion(
            document_id=document_id,
            version=version,
            s3_key=s3_key,
            mime_type=mime_type,
            size_bytes=size_bytes,
            created_by_account_id=created_by_account_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, version_id: UUID) -> DocumentVersion | None:
        return await self._session.get(DocumentVersion, version_id)

    async def latest(self, document_id: UUID) -> DocumentVersion | None:
        result = await self._session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_by_document(self, document_id: UUID) -> list[DocumentVersion]:
        result = await self._session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version.asc())
        )
        return list(result.scalars().all())


class ProcessingJobRepository:
    """SQL access for ``document_processing_jobs``; never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        document_id: UUID,
        document_version_id: UUID | None,
        job_type: ProcessingJobType,
    ) -> DocumentProcessingJob:
        job = DocumentProcessingJob(
            document_id=document_id,
            document_version_id=document_version_id,
            job_type=job_type,
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def get(self, job_id: UUID) -> DocumentProcessingJob | None:
        return await self._session.get(DocumentProcessingJob, job_id)

    async def get_by_version(
        self, document_version_id: UUID
    ) -> DocumentProcessingJob | None:
        result = await self._session.execute(
            select(DocumentProcessingJob)
            .where(DocumentProcessingJob.document_version_id == document_version_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_by_document(self, document_id: UUID) -> list[DocumentProcessingJob]:
        result = await self._session.execute(
            select(DocumentProcessingJob)
            .where(DocumentProcessingJob.document_id == document_id)
            .order_by(DocumentProcessingJob.created_at.desc())
        )
        return list(result.scalars().all())


class ExtractionRepository:
    """SQL access for ``document_extractions``; never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, extraction: DocumentExtraction) -> DocumentExtraction:
        self._session.add(extraction)
        await self._session.flush()
        return extraction

    async def get(self, extraction_id: UUID) -> DocumentExtraction | None:
        return await self._session.get(DocumentExtraction, extraction_id)

    async def list_by_document(self, document_id: UUID) -> list[DocumentExtraction]:
        result = await self._session.execute(
            select(DocumentExtraction)
            .where(DocumentExtraction.document_id == document_id)
            .order_by(DocumentExtraction.created_at.desc())
        )
        return list(result.scalars().all())
