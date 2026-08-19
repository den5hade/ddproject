from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.dependencies.auth import CurrentAccount
from app.dependencies.documents import JobServiceDep
from app.domain.medical import DocumentAccessDeniedError, DocumentNotFoundError, JobNotFoundError
from app.models.processing_job import DocumentProcessingJob
from app.schemas.document import JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


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


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    account: CurrentAccount,
    service: JobServiceDep,
) -> JobResponse:
    try:
        job = await service.get_job(account, job_id)
    except (JobNotFoundError, DocumentNotFoundError, DocumentAccessDeniedError) as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if isinstance(exc, (JobNotFoundError, DocumentNotFoundError))
            else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return _job_response(job)