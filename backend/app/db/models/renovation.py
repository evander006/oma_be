"""Renovation, design-session, estimate, and loyalty ORM models."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class RoomAnalysis(Base, TimestampMixin):
    __tablename__ = "room_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(Integer, ForeignKey("rooms.id"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="completed")


class DesignSession(Base, TimestampMixin):
    __tablename__ = "design_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    room_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("rooms.id"), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    style: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    budget: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="draft")
    latest_analysis_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("room_analyses.id"), nullable=True
    )

    versions: Mapped[list["DesignVersion"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class DesignVersion(Base, TimestampMixin):
    __tablename__ = "design_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("design_sessions.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analysis_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_photo_ids_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generation_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    generation_status: Mapped[str] = mapped_column(String(64), default="pending")
    # pending | processing | completed | failed | unavailable
    limitations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    warnings: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)

    session: Mapped[DesignSession] = relationship(back_populates="versions")
    selected_products: Mapped[list["SelectedDesignProduct"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )
    visualizations: Mapped[list["GeneratedVisualization"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class SelectedDesignProduct(Base, TimestampMixin):
    __tablename__ = "selected_design_products"
    __table_args__ = (
        UniqueConstraint("version_id", "product_id", name="uq_design_version_product"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(Integer, ForeignKey("design_versions.id"), index=True)
    product_id: Mapped[str] = mapped_column(String(64), ForeignKey("products.id"), index=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    reference_image_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    version: Mapped[DesignVersion] = relationship(back_populates="selected_products")


class GeneratedVisualization(Base, TimestampMixin):
    __tablename__ = "generated_visualizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(Integer, ForeignKey("design_versions.id"), index=True)
    relative_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="pending")
    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    disclaimer: Mapped[str] = mapped_column(
        Text,
        default=(
            "Концепт-визуализация. Не является точным доказательством внешнего вида, "
            "габаритов или возможности установки выбранных товаров."
        ),
    )

    version: Mapped[DesignVersion] = relationship(back_populates="visualizations")


class RenovationService(Base, TimestampMixin):
    __tablename__ = "renovation_services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # м², шт, час
    # Development price rules — not official OMA contractor rates.
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="BYN")
    price_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_turnkey_eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    is_standalone: Mapped[bool] = mapped_column(Boolean, default=True)


class RenovationProject(Base, TimestampMixin):
    __tablename__ = "renovation_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    property_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("properties.id"), nullable=True
    )
    room_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("rooms.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    renovation_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    scope: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # turnkey|partial|standalone
    area_m2: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    room_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    building_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    condition: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    work_categories_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    budget_min: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    budget_max: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    timeline_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    style_preferences: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    materials_preferences: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    customer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="draft")
    status_history_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    work_items: Mapped[list["RenovationWorkItem"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    requests: Mapped[list["RenovationRequest"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    estimates: Mapped[list["Estimate"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class RenovationWorkItem(Base, TimestampMixin):
    __tablename__ = "renovation_work_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("renovation_projects.id"), index=True)
    service_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("renovation_services.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    project: Mapped[RenovationProject] = relationship(back_populates="work_items")


class RenovationRequest(Base, TimestampMixin):
    __tablename__ = "renovation_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    project_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("renovation_projects.id"), nullable=True
    )
    request_type: Mapped[str] = mapped_column(String(64), default="turnkey")  # turnkey|standalone
    status: Mapped[str] = mapped_column(String(64), default="draft")
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    project: Mapped[Optional[RenovationProject]] = relationship(back_populates="requests")


class InstallationRequest(Base, TimestampMixin):
    __tablename__ = "installation_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    product_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("products.id"), nullable=True
    )
    service_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("renovation_services.id"), nullable=True
    )
    room_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("rooms.id"), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    preferred_dates: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="submitted")
    # Not a confirmed booking unless a real scheduling system confirms it.
    scheduling_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class Estimate(Base, TimestampMixin):
    __tablename__ = "estimates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    project_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("renovation_projects.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(64), default="preliminary")
    # preliminary | incomplete | consultation_required | confirmed
    currency: Mapped[str] = mapped_column(String(8), default="BYN")
    product_subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    labor_subtotal: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    additional_costs: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    unknown_costs_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    disclaimer: Mapped[str] = mapped_column(
        Text,
        default="Предварительная оценка. Не является подтверждённой сметой подрядчика.",
    )

    project: Mapped[Optional[RenovationProject]] = relationship(back_populates="estimates")
    lines: Mapped[list["EstimateLine"]] = relationship(
        back_populates="estimate", cascade="all, delete-orphan"
    )


class EstimateLine(Base, TimestampMixin):
    __tablename__ = "estimate_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    estimate_id: Mapped[int] = mapped_column(Integer, ForeignKey("estimates.id"), index=True)
    line_type: Mapped[str] = mapped_column(String(64), default="product")  # product|labor|other
    product_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("products.id"), nullable=True
    )
    service_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("renovation_services.id"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("1"))
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)

    estimate: Mapped[Estimate] = relationship(back_populates="lines")


class LoyaltyAccount(Base, TimestampMixin):
    __tablename__ = "loyalty_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    tier: Mapped[str] = mapped_column(String(64), default="standard")
    # Development configuration — not official OMA loyalty rules.
    program_label: Mapped[str] = mapped_column(
        String(128), default="OMA Dom development loyalty (demo rules)"
    )

    transactions: Mapped[list["LoyaltyTransaction"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class LoyaltyTransaction(Base, TimestampMixin):
    __tablename__ = "loyalty_transactions"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_loyalty_idempotency"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("loyalty_accounts.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)  # earn|redeem|reversal
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    order_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("orders.id"), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    account: Mapped[LoyaltyAccount] = relationship(back_populates="transactions")
