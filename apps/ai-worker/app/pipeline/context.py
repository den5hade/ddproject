"""Per-job processing context shared across pipeline stages."""

from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class ProcessingContext:
    """State threaded through a single document's pipeline run."""

    document_id: UUID
    document_version_id: UUID | None
    patient_id: UUID
    client_type: str = ""
    attributes: dict = field(default_factory=dict)