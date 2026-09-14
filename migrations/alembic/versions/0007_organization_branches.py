"""Add organization_branches table

Phase 2 of the organization-domain integration: organizations gain 1:N
branches. Branches are soft-deactivated (status `INACTIVE`), never deleted,
so historical references survive. `(organization_id, code)` is unique per
organization; cross-organization branches are isolated by scoping every
query through the organization id.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> sa.Uuid:
    return sa.Uuid()


def _ts() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "organization_branches",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("organization_id", _uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_branches_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_branches")),
    )
    op.create_index(
        op.f("ix_organization_branches_organization_id"),
        "organization_branches",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("uq_organization_branches_org_code"),
        "organization_branches",
        ["organization_id", "code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("uq_organization_branches_org_code"),
        table_name="organization_branches",
    )
    op.drop_index(
        op.f("ix_organization_branches_organization_id"),
        table_name="organization_branches",
    )
    op.drop_table("organization_branches")