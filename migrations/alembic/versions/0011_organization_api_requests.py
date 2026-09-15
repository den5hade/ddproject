"""Add organization_api_requests table

Phase 4c of the organization-domain integration: a high-volume, non-PII HTTP
access log for ``/integration/*`` requests (spec §24). ``request_id`` is the
X-Request-Id echoed on the response. ``organization_id``/``api_key_id`` are
nullable: requests that failed before authentication succeeded carry NULLs
(best-effort monitoring), and revoking a key does not erase its usage history
(api_key_id FK ondelete SET NULL).

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> sa.Uuid:
    return sa.Uuid()


def _ts() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "organization_api_requests",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("organization_id", _uuid(), nullable=True),
        sa.Column("api_key_id", _uuid(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_api_requests_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["api_key_id"],
            ["organization_api_keys.id"],
            name=op.f("fk_organization_api_requests_api_key_id_organization_api_keys"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_api_requests")),
    )
    op.create_index(
        op.f("ix_organization_api_requests_organization_id"),
        "organization_api_requests",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_organization_api_requests_api_key_id"),
        "organization_api_requests",
        ["api_key_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_organization_api_requests_created_at"),
        "organization_api_requests",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_organization_api_requests_created_at"),
        table_name="organization_api_requests",
    )
    op.drop_index(
        op.f("ix_organization_api_requests_api_key_id"),
        table_name="organization_api_requests",
    )
    op.drop_index(
        op.f("ix_organization_api_requests_organization_id"),
        table_name="organization_api_requests",
    )
    op.drop_table("organization_api_requests")