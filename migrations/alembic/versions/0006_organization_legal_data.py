"""Add legal data and verification status to organizations

Phase 1 of the organization-domain integration: organizations gain the
legal identifiers (INN/OGRN) with unique indexes, contact/legal-address
fields and a verification-status lifecycle column. All new columns are
nullable for existing rows except `verification_status`, which is backfilled
with the enum member name `UNVERIFIED` (SQLAlchemy stores str-Enum members
by name; see `app/models/organization.py` for the enum definition).

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations", sa.Column("inn", sa.String(length=12), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("ogrn", sa.String(length=13), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("legal_address", sa.Text(), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("email", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("phone", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("website", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "organizations",
        sa.Column(
            "verification_status",
            sa.String(length=16),
            nullable=False,
            server_default="UNVERIFIED",
        ),
    )
    op.create_index("uq_organizations_inn", "organizations", ["inn"], unique=True)
    op.create_index("uq_organizations_ogrn", "organizations", ["ogrn"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_organizations_ogrn", table_name="organizations")
    op.drop_index("uq_organizations_inn", table_name="organizations")
    op.drop_column("organizations", "verification_status")
    op.drop_column("organizations", "website")
    op.drop_column("organizations", "phone")
    op.drop_column("organizations", "email")
    op.drop_column("organizations", "legal_address")
    op.drop_column("organizations", "ogrn")
    op.drop_column("organizations", "inn")