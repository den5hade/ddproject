"""Simplify person: replace name parts with single name, add biometrics

Replaces first_name / last_name / middle_name with a single `name` column.
Adds city, profession, height, weight.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add new columns (nullable first for data migration)
    op.add_column("persons", sa.Column("name", sa.String(255), nullable=True))
    op.add_column("persons", sa.Column("city", sa.String(255), nullable=True))
    op.add_column("persons", sa.Column("profession", sa.String(255), nullable=True))
    op.add_column("persons", sa.Column("height", sa.Float(), nullable=True))
    op.add_column("persons", sa.Column("weight", sa.Float(), nullable=True))

    # Migrate data: build name from existing parts
    op.execute(
        "UPDATE persons SET name = TRIM(CONCAT_WS(' ', first_name, middle_name, last_name))"
    )
    # Fallback for empty results
    op.execute("UPDATE persons SET name = '' WHERE name IS NULL")

    # Drop old columns
    op.drop_column("persons", "first_name")
    op.drop_column("persons", "last_name")
    op.drop_column("persons", "middle_name")

    # Make name NOT NULL now that data is populated
    op.alter_column("persons", "name", nullable=False, server_default="''")


def downgrade() -> None:
    op.alter_column("persons", "name", nullable=True)
    op.drop_column("persons", "weight")
    op.drop_column("persons", "height")
    op.drop_column("persons", "profession")
    op.drop_column("persons", "city")

    # Recreate old columns
    op.add_column("persons", sa.Column("first_name", sa.String(255), nullable=False, server_default=""))
    op.add_column("persons", sa.Column("last_name", sa.String(255), nullable=False, server_default=""))
    op.add_column("persons", sa.Column("middle_name", sa.String(255), nullable=True))

    # Best-effort reverse migration (name → first_name)
    op.execute("UPDATE persons SET first_name = name")
    op.drop_column("persons", "name")
