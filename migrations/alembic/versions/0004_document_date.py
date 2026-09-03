"""Add document_date to documents

Persists the medical document's actual date (when it was issued), extracted
from the canonical payload by the ai-worker, onto the `documents` table.
Null while the document is still processing or when the date is unknown.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("document_date", sa.DateTime(timezone=True), nullable=True),
    )

    # Best-effort backfill from the latest *succeeded* extraction's canonical
    # `document_date`. The value is emitted as "YYYY-MM-DD" by the LLM; cast to
    # a true date so ordering/formatting match new writes.
    #
    # NOTE: this filter originally used `status = 'succeeded'` (lowercase) which
    # matches nothing because SQLAlchemy's Enum(native_enum=False) stores the
    # uppercase name `SUCCEEDED`. The corrected backfill lives in 0005.
    op.execute(
        """
        UPDATE documents d
        SET document_date = CAST(
            NULLIF(ex.data->>'document_date', '') AS date
        )
        FROM (
            SELECT DISTINCT ON (document_id) document_id, data
            FROM document_extractions
            WHERE status = 'succeeded' AND data IS NOT NULL
            ORDER BY document_id, created_at DESC
        ) ex
        WHERE ex.document_id = d.id
        """
    )


def downgrade() -> None:
    op.drop_column("documents", "document_date")
