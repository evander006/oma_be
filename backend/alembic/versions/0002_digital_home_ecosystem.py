"""digital home ecosystem

Revision ID: 0002_digital_home_ecosystem
Revises: 0001_initial
Create Date: 2026-10-27
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_digital_home_ecosystem"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    with op.batch_alter_table("properties") as batch:
        batch.add_column(sa.Column("tenure", sa.String(length=32), nullable=True))
    with op.batch_alter_table("rooms") as batch:
        batch.add_column(sa.Column("wall_material", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("floor_material", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("ceiling_material", sa.String(length=255), nullable=True))

    op.create_table(
        "contractor_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=128), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("experience_years", sa.Integer(), nullable=True),
        sa.Column("rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
    )
    op.create_table(
        "contractor_specialties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "contractor_id",
            sa.Integer(),
            sa.ForeignKey("contractor_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("contractor_id", "code", name="uq_contractor_specialty"),
    )
    op.create_table(
        "contractor_portfolio_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "contractor_id",
            sa.Integer(),
            sa.ForeignKey("contractor_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("image_url", sa.String(length=1024), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
    )
    op.create_table(
        "contractor_favorites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "contractor_id",
            sa.Integer(),
            sa.ForeignKey("contractor_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *_timestamps(),
        sa.UniqueConstraint("user_id", "contractor_id", name="uq_contractor_favorite"),
    )
    op.create_table(
        "work_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "contractor_id", sa.Integer(), sa.ForeignKey("contractor_profiles.id"), nullable=False
        ),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=True),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("rooms.id"), nullable=True),
        sa.Column(
            "project_id", sa.Integer(), sa.ForeignKey("renovation_projects.id"), nullable=True
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("budget_byn", sa.Numeric(12, 2), nullable=True),
        sa.Column("shared_fields_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("consent_granted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="submitted"),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_table(
        "material_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "work_order_id",
            sa.Integer(),
            sa.ForeignKey("work_orders.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "contractor_id", sa.Integer(), sa.ForeignKey("contractor_profiles.id"), nullable=False
        ),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="sent"),
        sa.Column("total_amount_byn", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="BYN"),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
    )
    op.create_table(
        "material_proposal_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.Integer(),
            sa.ForeignKey("material_proposals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", sa.String(length=64), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("product_name_snapshot", sa.String(length=512), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unit_price_byn", sa.Numeric(12, 2), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("proposal_id", "product_id", name="uq_proposal_product"),
    )
    op.create_table(
        "home_equipment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=True),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("rooms.id"), nullable=True),
        sa.Column("product_id", sa.String(length=64), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id"), nullable=True),
        sa.Column(
            "contractor_id", sa.Integer(), sa.ForeignKey("contractor_profiles.id"), nullable=True
        ),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="installed"),
        sa.Column("product_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("specifications_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("installed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("work_order_id", "product_id", name="uq_work_order_equipment"),
    )
    op.create_table(
        "home_history_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=True),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("rooms.id"), nullable=True),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id"), nullable=True),
        sa.Column(
            "contractor_id", sa.Integer(), sa.ForeignKey("contractor_profiles.id"), nullable=True
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "journey_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=128), nullable=False, unique=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
    )
    op.create_table(
        "journey_template_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey("journey_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("recommended_categories_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("reward_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reward_label", sa.String(length=255), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("template_id", "position", name="uq_journey_template_position"),
        sa.UniqueConstraint("template_id", "code", name="uq_journey_template_code"),
    )
    op.create_table(
        "journey_instances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("journey_templates.id"), nullable=False),
        sa.Column(
            "project_id", sa.Integer(), sa.ForeignKey("renovation_projects.id"), nullable=True
        ),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="active"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_table(
        "journey_step_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "journey_id",
            sa.Integer(),
            sa.ForeignKey("journey_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "step_id", sa.Integer(), sa.ForeignKey("journey_template_steps.id"), nullable=False
        ),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="pending"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reward_transaction_id",
            sa.Integer(),
            sa.ForeignKey("loyalty_transactions.id"),
            nullable=True,
        ),
        *_timestamps(),
        sa.UniqueConstraint("journey_id", "step_id", name="uq_journey_step_progress"),
    )


def downgrade() -> None:
    for table in (
        "journey_step_progress",
        "journey_instances",
        "journey_template_steps",
        "journey_templates",
        "home_history_events",
        "home_equipment",
        "material_proposal_items",
        "material_proposals",
        "work_orders",
        "contractor_favorites",
        "contractor_portfolio_items",
        "contractor_specialties",
        "contractor_profiles",
    ):
        op.drop_table(table)
    with op.batch_alter_table("rooms") as batch:
        batch.drop_column("ceiling_material")
        batch.drop_column("floor_material")
        batch.drop_column("wall_material")
    with op.batch_alter_table("properties") as batch:
        batch.drop_column("tenure")
