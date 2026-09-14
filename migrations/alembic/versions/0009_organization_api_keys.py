"""Add organization_api_keys table

Phase 4 of the organization-domain integration: machine-to-machine API keys.
Only the key hash is persisted; the raw key is shown once on creation/rotation.
Delete = soft revoke; the full key format is ``ddorg_<env>_<secret>``.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> sa.Uuid:
    return sa.Uuid()


def _ts() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "organization_api_keys",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("organization_id", _uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("created_by_account_id", _uuid(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("expires_at", _ts(), nullable=True),
        sa.Column("revoked_at", _ts(), nullable=True),
        sa.Column("last_used_at", _ts(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_api_keys_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["accounts.id"],
            name=op.f("fk_organization_api_keys_created_by_account_id_accounts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_api_keys")),
    )
    op.create_index(
        op.f("ix_organization_api_keys_organization_id"),
        "organization_api_keys",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("uq_organization_api_keys_key_hash"),
        "organization_api_keys",
        ["key_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("uq_organization_api_keys_key_hash"),
        table_name="organization_api_keys",
    )
    op.drop_index(
        op.f("ix_organization_api_keys_organization_id"),
        table_name="organization_api_keys",
    )
    op.drop_table("organization_api_keys")