"""Add organization_licenses table

Phase 3 of the organization-domain integration: organizations gain multiple
licenses (line activity permits). Licenses keep full history -- DELETE is a
soft status change (REVOKED), never a row removal, and an expired license
keeps its number allocated (`(organization_id, license_number)` unique).
Columns follow the OC plan §4.3 (registry-ready schema without coupling the
domain to any external provider).

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> sa.Uuid:
    return sa.Uuid()


def _ts() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "organization_licenses",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("organization_id", _uuid(), nullable=False),
        sa.Column("license_number", sa.String(length=64), nullable=False),
        sa.Column("license_type", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("issued_at", sa.Date(), nullable=True),
        sa.Column("expires_at", sa.Date(), nullable=True),
        sa.Column("scope", sa.String(length=255), nullable=True),
        sa.Column("issuer", sa.String(length=255), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_licenses_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_licenses")),
    )
    op.create_index(
        op.f("ix_organization_licenses_organization_id"),
        "organization_licenses",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("uq_organization_licenses_org_number"),
        "organization_licenses",
        ["organization_id", "license_number"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("uq_organization_licenses_org_number"),
        table_name="organization_licenses",
    )
    op.drop_index(
        op.f("ix_organization_licenses_organization_id"),
        table_name="organization_licenses",
    )
    op.drop_table("organization_licenses")