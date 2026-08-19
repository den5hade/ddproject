import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.medical import JobNotFoundError
from app.models.processing_job import DocumentProcessingJob
from app.repositories.document import ProcessingJobRepository

logger = logging.getLogger("account_api.jobs")


class JobService:
    """Job status reads; access is enforced by the ABAC ``require_job_access``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._jobs = ProcessingJobRepository(session)

    async def get_job(self, job_id: UUID) -> DocumentProcessingJob:
        job = await self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError("job not found")
        return job

    async def list_jobs(self, document_id: UUID) -> list[DocumentProcessingJob]:
        return await self._jobs.list_by_document(document_id)


__all__ = ["JobService"]