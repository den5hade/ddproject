from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.medical import ExtractionStatus
from app.models.utils import utcnow


class DocumentExtraction(Base):
    """Structured data extracted from a document by AI (DB_MODELS.md #20)."""

    __tablename__ = "document_extractions"

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
    schema_name: Mapped[str] = mapped_column(String(128), default="")
    schema_version: Mapped[str] = mapped_column(String(32), default="1")
    status: Mapped[ExtractionStatus] = mapped_column(
        Enum(ExtractionStatus, native_enum=False, length=16), default=ExtractionStatus.PENDING
    )
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )