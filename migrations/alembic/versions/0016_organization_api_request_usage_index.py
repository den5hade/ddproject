"""Add composite usage index on organization_api_requests

Phase 4h of the organization-domain integration: org-scoped, non-PII API-usage
monitoring. ``ix_organization_api_requests_org_created`` makes the daily
aggregation behind ``GET /organizations/me/api-usage`` (``organization_id`` +
``created_at`` time window, bucket by day) and the retention purge
(``created_at < cutoff``) index-covered. Kept alongside the single-column
indexes (whose names match the model's ``index=True`` declarations).

Revision ID: 0016
Revises: 0014 (current head; chain: ... 0013 -> 0015 -> 0014 -> 0016)
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_organization_api_requests_org_created"


def upgrade() -> None:
    op.create_index(
        _INDEX_NAME,
        "organization_api_requests",
        ["organization_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="organization_api_requests")