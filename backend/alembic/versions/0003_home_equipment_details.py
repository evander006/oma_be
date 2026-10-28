"""persist home equipment card details

Revision ID: 0003_home_equipment_details
Revises: 0002_digital_home_ecosystem
Create Date: 2026-10-27
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_home_equipment_details"
down_revision = "0002_digital_home_ecosystem"
branch_labels = None
depends_on = None


def _column_names() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("home_equipment")
    }


def upgrade() -> None:
    existing = _column_names()
    columns = (
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("serial_number", sa.String(length=255), nullable=True),
        sa.Column("warranty_until", sa.DateTime(timezone=True), nullable=True),
    )
    missing = [column for column in columns if column.name not in existing]
    if missing:
        with op.batch_alter_table("home_equipment") as batch:
            for column in missing:
                batch.add_column(column)


def downgrade() -> None:
    with op.batch_alter_table("home_equipment") as batch:
        batch.drop_column("warranty_until")
        batch.drop_column("serial_number")
        batch.drop_column("model")
        batch.drop_column("brand")
        batch.drop_column("category")
