"""Add organization upload batch tables

Phase 4e of the organization-domain integration: organizations submit many
documents in one batch. ``organization_upload_batches`` is the batch header
(org + API key + ``idempotency_key`` + counters + lifecycle timestamps);
``organization_upload_batch_items`` is the per-item ledger (patient_email,
document_type, external_id, branch_code, title, item status + error details).
Each item is processed in its own transaction, so a failed item never rolls
back the batch; item-level statuses track partial failures.

All status columns are plain VARCHAR with the enum member **name** as the
server default (``ACCEPTED`` / ``PENDING`` / ``OTHER``) because SQLAlchemy
stores str-Enum members by name (see ``app/models/organization.py`` and the
verified convention in 0006). Unique indexes follow the repo pattern: a
unique **index** (never a ``UniqueConstraint``) so SQLite batch mode works
and the constraint name matches the model.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> sa.Uuid:
    return sa.Uuid()


def _ts() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def _batch_idem_not_null() -> str:
    return "idempotency_key IS NOT NULL"


def upgrade() -> None:
    op.create_table(
        "organization_upload_batches",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("organization_id", _uuid(), nullable=False),
        sa.Column("api_key_id", _uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="ACCEPTED",
        ),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "accepted_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "failed_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("completed_at", _ts(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_upload_batches_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["api_key_id"],
            ["organization_api_keys.id"],
            name=op.f("fk_organization_upload_batches_api_key_id_organization_api_keys"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_upload_batches")),
    )
    op.create_index(
        op.f("ix_organization_upload_batches_organization_id"),
        "organization_upload_batches",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_organization_upload_batches_api_key_id"),
        "organization_upload_batches",
        ["api_key_id"],
        unique=False,
    )
    op.create_index(
        op.f("uq_organization_upload_batches_org_idem"),
        "organization_upload_batches",
        ["organization_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text(_batch_idem_not_null()),
        sqlite_where=sa.text(_batch_idem_not_null()),
    )

    op.create_table(
        "organization_upload_batch_items",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("batch_id", _uuid(), nullable=False),
        sa.Column("document_id", _uuid(), nullable=True),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("patient_email", sa.String(length=255), nullable=False),
        sa.Column(
            "document_type",
            sa.String(length=32),
            nullable=False,
            server_default="OTHER",
        ),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("branch_code", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["organization_upload_batches.id"],
            name=op.f(
                "fk_organization_upload_batch_items_batch_id_organization_upload_batches"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_organization_upload_batch_items_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_organization_upload_batch_items")
        ),
    )
    op.create_index(
        op.f("ix_organization_upload_batch_items_batch_id"),
        "organization_upload_batch_items",
        ["batch_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_organization_upload_batch_items_document_id"),
        "organization_upload_batch_items",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("uq_organization_upload_batch_items_batch_index"),
        "organization_upload_batch_items",
        ["batch_id", "item_index"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("uq_organization_upload_batch_items_batch_index"),
        table_name="organization_upload_batch_items",
    )
    op.drop_index(
        op.f("ix_organization_upload_batch_items_document_id"),
        table_name="organization_upload_batch_items",
    )
    op.drop_index(
        op.f("ix_organization_upload_batch_items_batch_id"),
        table_name="organization_upload_batch_items",
    )
    op.drop_table("organization_upload_batch_items")
    op.drop_index(
        op.f("uq_organization_upload_batches_org_idem"),
        table_name="organization_upload_batches",
    )
    op.drop_index(
        op.f("ix_organization_upload_batches_api_key_id"),
        table_name="organization_upload_batches",
    )
    op.drop_index(
        op.f("ix_organization_upload_batches_organization_id"),
        table_name="organization_upload_batches",
    )
    op.drop_table("organization_upload_batches")