from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.bus import get_publisher
from app.core.config import settings
from app.core.database import get_db
from app.services.documents import DocumentService
from app.services.jobs import JobService
from app.services.storage import StorageService


async def reject_oversized_upload(request: Request) -> None:
    """Reject requests whose declared size would exceed ``max_upload_bytes``.

    Runs before FastAPI parses the multipart body so oversized uploads are
    refused without being spooled to disk.
    """
    content_length = request.headers.get("content-length")
    if (
        content_length
        and content_length.isdigit()
        and int(content_length) > settings.max_upload_bytes
    ):
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"file exceeds the maximum of {settings.max_upload_bytes} bytes",
        )


async def get_storage_service() -> StorageService:
    return StorageService.from_settings()


async def get_document_service(
    session: AsyncSession = Depends(get_db),
) -> DocumentService:
    publisher = await get_publisher()
    return DocumentService(
        session=session,
        publisher=publisher,
        storage=StorageService.from_settings(),
    )


async def get_job_service(
    session: AsyncSession = Depends(get_db),
) -> JobService:
    return JobService(session)


DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
JobServiceDep = Annotated[JobService, Depends(get_job_service)]
StorageServiceDep = Annotated[StorageService, Depends(get_storage_service)]