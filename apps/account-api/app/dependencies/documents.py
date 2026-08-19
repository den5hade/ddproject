from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.bus import get_publisher
from app.core.database import get_db
from app.services.documents import DocumentService
from app.services.jobs import JobService
from app.services.storage import StorageService


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