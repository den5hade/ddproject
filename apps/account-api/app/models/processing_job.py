from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.medical import ProcessingJobStatus, ProcessingJobType
from app.models.utils import utcnow


class DocumentProcessingJob(Base):
    """Track async document processing (conversion / extraction / embedding, #19)."""

    __tablename__ = "document_processing_jobs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    job_type: Mapped[ProcessingJobType] = mapped_column(
        Enum(ProcessingJobType, native_enum=False, length=32)
    )
    status: Mapped[ProcessingJobStatus] = mapped_column(
        Enum(ProcessingJobStatus, native_enum=False, length=16),
        default=ProcessingJobStatus.QUEUED,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )