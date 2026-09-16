"""Add organization document source columns

Phase 4d of the organization-domain integration: documents uploaded by an
organization through the integration API carry the submitting organization
(``organization_id``, FK -> organizations ondelete SET NULL), the optional
branch (``organization_branch_id``, FK -> organization_branches ondelete SET
NULL), the caller-provided ``external_id`` and ``idempotency_key`` (client
correlation identifiers), and the original ``provided_document_type`` as sent
by the organization (the canonical ``document_type`` stays in ``documents``).

Partial unique indexes enforce one row per organization / external_id and per
organization / idempotency_key while leaving self-service documents (all these
columns NULL) untouched.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_not_null() -> str:
    return "organization_id IS NOT NULL"


def upgrade() -> None:
    # SQLite cannot ALTER FOREIGN KEYs directly -> table recreation (batch mode);
    # the FK constraints must be named (batch requirement).
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("organization_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_documents_organization_id_organizations"),
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_documents_organization_id"),
            ["organization_id"],
            unique=False,
        )
        batch_op.add_column(
            sa.Column("organization_branch_id", sa.Uuid(), nullable=True)
        )
        batch_op.create_foreign_key(
            op.f("fk_documents_organization_branch_id_organization_branches"),
            "organization_branches",
            ["organization_branch_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_documents_organization_branch_id"),
            ["organization_branch_id"],
            unique=False,
        )
        batch_op.add_column(sa.Column("external_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column("provided_document_type", sa.String(length=64), nullable=True)
        )
        batch_op.create_index(
            op.f("uq_documents_organization_external_id"),
            ["organization_id", "external_id"],
            unique=True,
            postgresql_where=sa.text(_is_not_null()),
            sqlite_where=sa.text(_is_not_null()),
        )
        batch_op.create_index(
            op.f("uq_documents_organization_idempotency_key"),
            ["organization_id", "idempotency_key"],
            unique=True,
            postgresql_where=sa.text(_is_not_null()),
            sqlite_where=sa.text(_is_not_null()),
        )


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_index(op.f("uq_documents_organization_idempotency_key"))
        batch_op.drop_index(op.f("uq_documents_organization_external_id"))
        batch_op.drop_column("provided_document_type")
        batch_op.drop_column("idempotency_key")
        batch_op.drop_column("external_id")
        batch_op.drop_index(op.f("ix_documents_organization_branch_id"))
        batch_op.drop_constraint(
            op.f("fk_documents_organization_branch_id_organization_branches"),
            type_="foreignkey",
        )
        batch_op.drop_column("organization_branch_id")
        batch_op.drop_index(op.f("ix_documents_organization_id"))
        batch_op.drop_constraint(
            op.f("fk_documents_organization_id_organizations"),
            type_="foreignkey",
        )
        batch_op.drop_column("organization_id")