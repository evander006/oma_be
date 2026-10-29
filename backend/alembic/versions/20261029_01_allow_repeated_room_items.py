"""Allow multiple instances of the same catalog item in a room design draft.

Older databases may still have the unique constraint from the first draft schema.
The current ORM allows repeat items (e.g. four chairs or several lamps).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261029_01"
down_revision = "0003_home_equipment_details"
branch_labels = None
depends_on = None


def _constraint_exists(bind, name: str) -> bool:
    inspector = sa.inspect(bind)
    if "room_design_placements" not in inspector.get_table_names():
        return False
    return any(
        item.get("name") == name
        for item in inspector.get_unique_constraints("room_design_placements")
    )


def upgrade() -> None:
    bind = op.get_bind()
    if _constraint_exists(bind, "uq_room_design_product"):
        with op.batch_alter_table("room_design_placements") as batch:
            batch.drop_constraint("uq_room_design_product", type_="unique")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "room_design_placements" not in inspector.get_table_names():
        return
    if not _constraint_exists(bind, "uq_room_design_product"):
        with op.batch_alter_table("room_design_placements") as batch:
            batch.create_unique_constraint(
                "uq_room_design_product", ["room_id", "product_id"]
            )
