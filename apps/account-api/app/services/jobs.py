import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.medical import JobNotFoundError
from app.models.account import Account
from app.models.processing_job import DocumentProcessingJob
from app.repositories.document import DocumentRepository, ProcessingJobRepository
from app.services.documents import DocumentService

logger = logging.getLogger("account_api.jobs")


class JobService:
    """Job status reads; access is delegated to DocumentService checks."""

    def __init__(
        self,
        session: AsyncSession,
        document_service: DocumentService | None = None,
    ) -> None:
        self._session = session
        self._jobs = ProcessingJobRepository(session)
        self._documents = DocumentRepository(session)
        self._document_service = document_service

    def _docs(self, session: AsyncSession) -> DocumentService:
        if self._document_service is None:
            self._document_service = DocumentService(session)
        return self._document_service

    async def get_job(self, account: Account, job_id: UUID) -> DocumentProcessingJob:
        job = await self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError("job not found")
        await self._docs(self._session).get_document(account, job.document_id)
        return job

    async def list_jobs(
        self, account: Account, document_id: UUID
    ) -> list[DocumentProcessingJob]:
        await self._docs(self._session).get_document(account, document_id)
        return await self._jobs.list_by_document(document_id)


__all__ = ["JobService"]