from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.http_errors import raise_for
from app.dependencies.access import require_job_access
from app.dependencies.documents import JobServiceDep
from app.domain.medical import JobNotFoundError
from app.schemas.document import JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get(
    "/{job_id}", response_model=JobResponse, dependencies=[Depends(require_job_access())]
)
async def get_job(
    job_id: UUID,
    service: JobServiceDep,
) -> JobResponse:
    try:
        job = await service.get_job(job_id)
    except JobNotFoundError as exc:
        raise_for(exc)
    return JobResponse.model_validate(job)
