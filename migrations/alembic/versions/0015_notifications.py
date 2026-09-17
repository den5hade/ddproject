"""Add notifications table

Phase 4f of the organization-domain integration: when an organization-sourced
document finishes processing (or fails), account-api creates a ``notifications``
row and emits ``notification.requested``; notification-worker delivers the email
and reports back on ``notification.delivered`` so the row moves
PENDING -> SENT/FAILED (and later READ when the client opens it).

The row carries only delivery and reference data (recipient account, source
organization, rendered subject/body, resource ids) — never medical data
(diagnosis, values, filenames or canonical JSON). ``organization_id`` is
SET NULL so history survives an org deletion; ``account_id`` uses CASCADE as
delivery is tied to the account.

Status/type/channel columns are plain VARCHAR with the enum member **name**
as the server default (``PENDING`` / ``EMAIL`` / ``document``) following the
verified convention in 0006/0013: SQLAlchemy stores str-Enum members by name.

Revision ID: 0015
Revises: 0013
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> sa.Uuid:
    return sa.Uuid()


def _ts() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("account_id", _uuid(), nullable=False),
        sa.Column("organization_id", _uuid(), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column(
            "channel",
            sa.String(length=16),
            nullable=False,
            server_default="EMAIL",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column(
            "resource_type",
            sa.String(length=32),
            nullable=False,
            server_default="document",
        ),
        sa.Column("resource_id", _uuid(), nullable=False),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("sent_at", _ts(), nullable=True),
        sa.Column("read_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_notifications_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_notifications_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(
        op.f("ix_notifications_account_id"),
        "notifications",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_organization_id"),
        "notifications",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_created_at"),
        "notifications",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notifications_created_at"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_organization_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_account_id"), table_name="notifications")
    op.drop_table("notifications")