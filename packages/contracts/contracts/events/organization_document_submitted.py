from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field


def _occurred_at() -> datetime:
    return datetime.now(UTC)


class OrganizationDocumentSubmitted(BaseModel):
    """Published by account-api on the organization domain (routing key
    ``organization.document.submitted``) when an organization uploads a document
    through the integration API.

    Carries the organization/branch-independent correlation identifiers so
    downstream organization consumers can tie the submission back to the
    caller's ``external_id`` without re-reading the database.
    """

    event_id: UUID
    occurred_at: datetime = Field(default_factory=_occurred_at)
    event_version: int = 1
    organization_id: UUID
    document_id: UUID
    patient_id: UUID
    external_id: str | None = None
    document_type: str | None = None