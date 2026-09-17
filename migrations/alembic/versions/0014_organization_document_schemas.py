"""Add organization document schemas table

Phase 4g of the organization-domain integration: an organization drafts and
publishes versioned JSON-Schema definitions that describe the structure of its
own document submissions. ``organization_document_schemas`` is a **metadata
registry only** — it never replaces or couples to the platform canonical
schema (spec §23); LLM consumption is deferred to a later phase.

Versioning: versions are monotonic per ``(organization_id, name)``; each
version is its own row, so ``uq_organization_document_schemas_org_name_ver``
(a unique **index**, per the repo convention) guarantees at most one row per
(org, name, version). ``status`` moves ``DRAFT -> PUBLISHED`` on publish and
a published row is immutable. ``document_type`` is the platform ``DocumentType``
enum stored as VARCHAR with the enum member name (``OTHER``) as the default,
following the verified convention in 0006/0013.

This revision keeps the phased ``0014`` name but chains from ``0015`` (the
Phase 4f notifications head) so the alembic chain stays linear:
``0013 -> 0015 -> 0014``.

Revision ID: 0014
Revises: 0015
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> sa.Uuid:
    return sa.Uuid()


def _ts() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "organization_document_schemas",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("organization_id", _uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "document_type",
            sa.String(length=32),
            nullable=False,
            server_default="OTHER",
        ),
        sa.Column("schema_definition", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("created_by_account_id", _uuid(), nullable=True),
        sa.Column("published_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f(
                "fk_organization_document_schemas_organization_id_organizations"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["accounts.id"],
            name=op.f(
                "fk_organization_document_schemas_created_by_account_id_accounts"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_document_schemas")),
    )
    op.create_index(
        op.f("ix_organization_document_schemas_organization_id"),
        "organization_document_schemas",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_organization_document_schemas_created_at"),
        "organization_document_schemas",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("uq_organization_document_schemas_org_name_ver"),
        "organization_document_schemas",
        ["organization_id", "name", "version"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("uq_organization_document_schemas_org_name_ver"),
        table_name="organization_document_schemas",
    )
    op.drop_index(
        op.f("ix_organization_document_schemas_created_at"),
        table_name="organization_document_schemas",
    )
    op.drop_index(
        op.f("ix_organization_document_schemas_organization_id"),
        table_name="organization_document_schemas",
    )
    op.drop_table("organization_document_schemas")