"""Add admin onboarding fields: created_by_account_id + membership role

Phase 4a of the organization-domain integration: organizations gain
``created_by_account_id`` (the System Admin who provisioned the organization,
FK -> accounts ondelete SET NULL) and ``organization_memberships.role``
(OrganizationMembershipRole member name, existing rows default to ``member``).
Onboarding never grants a global ``organization_admin`` AccountRole; the
membership role authorizes org access (migrated in Phase 4b).

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> sa.Uuid:
    return sa.Uuid()


def upgrade() -> None:
    # SQLite cannot ALTER FOREIGN KEYs directly -> table recreation (batch mode);
    # the FK constraint must be named (batch requirement).
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.add_column(
            sa.Column("created_by_account_id", _uuid(), nullable=True)
        )
        batch_op.create_foreign_key(
            op.f("fk_organizations_created_by_account_id_accounts"),
            "accounts",
            ["created_by_account_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_organizations_created_by_account_id"),
            ["created_by_account_id"],
            unique=False,
        )
    op.add_column(
        "organization_memberships",
        sa.Column(
            "role",
            sa.String(length=16),
            nullable=False,
            server_default="MEMBER",
        ),
    )


def downgrade() -> None:
    op.drop_column("organization_memberships", "role")
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.drop_index(
            op.f("ix_organizations_created_by_account_id")
        )
        batch_op.drop_constraint(
            op.f("fk_organizations_created_by_account_id_accounts"),
            type_="foreignkey",
        )
        batch_op.drop_column("created_by_account_id")