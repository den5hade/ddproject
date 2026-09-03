"""Backfill document_date from extraction data (correct status case)

Migration 0004 added the `document_date` column but its backfill filter used
`status = 'succeeded'` while the SQLAlchemy enum (native_enum=False) stores
the value as uppercase `SUCCEEDED` — so zero rows matched. This migration
re-runs the backfill with the correct case. Idempotent: it only fills rows
that still have NULL document_date and a succeeded extraction carrying one.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE documents d
        SET document_date = CAST(
            NULLIF(ex.data->>'document_date', '') AS date
        )
        FROM (
            SELECT DISTINCT ON (document_id) document_id, data
            FROM document_extractions
            WHERE status = 'SUCCEEDED' AND data IS NOT NULL
            ORDER BY document_id, created_at DESC
        ) ex
        WHERE ex.document_id = d.id
          AND d.document_date IS NULL
          AND NULLIF(ex.data->>'document_date', '') IS NOT NULL
        """
    )


def downgrade() -> None:
    # No-op: backfills are data migrations; nothing to reverse.
    pass
