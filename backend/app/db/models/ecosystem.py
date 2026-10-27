"""OMA digital-home ecosystem ORM models.

The existing application intentionally remains a small synchronous FastAPI/
SQLAlchemy service.  These models extend that same architecture with the
minimum persistent entities needed to connect a home passport, demo
contractors, structured work orders, material proposals and project journeys.
"""
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


class ContractorProfile(Base, TimestampMixin):
    __tablename__ = "contractor_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    experience_years: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rating: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2), nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)

    specialties: Mapped[list["ContractorSpecialty"]] = relationship(
        back_populates="contractor", cascade="all, delete-orphan"
    )
    portfolio: Mapped[list["ContractorPortfolioItem"]] = relationship(
        back_populates="contractor", cascade="all, delete-orphan"
    )


class ContractorSpecialty(Base, TimestampMixin):
    __tablename__ = "contractor_specialties"
    __table_args__ = (
        UniqueConstraint("contractor_id", "code", name="uq_contractor_specialty"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contractor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contractor_profiles.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    contractor: Mapped[ContractorProfile] = relationship(back_populates="specialties")


class ContractorPortfolioItem(Base, TimestampMixin):
    __tablename__ = "contractor_portfolio_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contractor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contractor_profiles.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    image_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)

    contractor: Mapped[ContractorProfile] = relationship(back_populates="portfolio")


class ContractorFavorite(Base, TimestampMixin):
    __tablename__ = "contractor_favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "contractor_id", name="uq_contractor_favorite"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    contractor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contractor_profiles.id", ondelete="CASCADE"), index=True
    )


class WorkOrder(Base, TimestampMixin):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    contractor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contractor_profiles.id"), index=True
    )
    property_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("properties.id"), nullable=True, index=True
    )
    room_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("rooms.id"), nullable=True, index=True
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("renovation_projects.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    budget_byn: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    shared_fields_json: Mapped[str] = mapped_column(Text, default="[]")
    consent_granted: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(64), default="submitted", index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    contractor: Mapped[ContractorProfile] = relationship()
    property: Mapped[Optional["Property"]] = relationship()  # type: ignore[name-defined]
    room: Mapped[Optional["Room"]] = relationship()  # type: ignore[name-defined]
    project: Mapped[Optional["RenovationProject"]] = relationship()  # type: ignore[name-defined]
    proposal: Mapped[Optional["MaterialProposal"]] = relationship(
        back_populates="work_order", cascade="all, delete-orphan", uselist=False
    )


class MaterialProposal(Base, TimestampMixin):
    __tablename__ = "material_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_order_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    contractor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contractor_profiles.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(64), default="sent")
    total_amount_byn: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(8), default="BYN")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)

    work_order: Mapped[WorkOrder] = relationship(back_populates="proposal")
    items: Mapped[list["MaterialProposalItem"]] = relationship(
        back_populates="proposal", cascade="all, delete-orphan"
    )


class MaterialProposalItem(Base, TimestampMixin):
    __tablename__ = "material_proposal_items"
    __table_args__ = (
        UniqueConstraint("proposal_id", "product_id", name="uq_proposal_product"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("material_proposals.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[str] = mapped_column(String(64), ForeignKey("products.id"), index=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(512), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price_byn: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)

    proposal: Mapped[MaterialProposal] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()  # type: ignore[name-defined]


class HomeEquipment(Base, TimestampMixin):
    __tablename__ = "home_equipment"
    __table_args__ = (
        UniqueConstraint("work_order_id", "product_id", name="uq_work_order_equipment"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    property_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("properties.id"), nullable=True, index=True
    )
    room_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("rooms.id"), nullable=True, index=True
    )
    product_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("products.id"), nullable=True, index=True
    )
    work_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("work_orders.id"), nullable=True, index=True
    )
    contractor_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contractor_profiles.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(64), default="installed")
    product_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    specifications_json: Mapped[str] = mapped_column(Text, default="{}")
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class HomeHistoryEvent(Base, TimestampMixin):
    __tablename__ = "home_history_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    property_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("properties.id"), nullable=True, index=True
    )
    room_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("rooms.id"), nullable=True, index=True
    )
    work_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("work_orders.id"), nullable=True, index=True
    )
    contractor_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contractor_profiles.id"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class JourneyTemplate(Base, TimestampMixin):
    __tablename__ = "journey_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)

    steps: Mapped[list["JourneyTemplateStep"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class JourneyTemplateStep(Base, TimestampMixin):
    __tablename__ = "journey_template_steps"
    __table_args__ = (
        UniqueConstraint("template_id", "position", name="uq_journey_template_position"),
        UniqueConstraint("template_id", "code", name="uq_journey_template_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("journey_templates.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    recommended_categories_json: Mapped[str] = mapped_column(Text, default="[]")
    reward_points: Mapped[int] = mapped_column(Integer, default=0)
    reward_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    template: Mapped[JourneyTemplate] = relationship(back_populates="steps")


class JourneyInstance(Base, TimestampMixin):
    __tablename__ = "journey_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    template_id: Mapped[int] = mapped_column(Integer, ForeignKey("journey_templates.id"), index=True)
    project_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("renovation_projects.id"), nullable=True, index=True
    )
    property_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("properties.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(64), default="active")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    template: Mapped[JourneyTemplate] = relationship()
    progress: Mapped[list["JourneyStepProgress"]] = relationship(
        back_populates="journey", cascade="all, delete-orphan"
    )


class JourneyStepProgress(Base, TimestampMixin):
    __tablename__ = "journey_step_progress"
    __table_args__ = (
        UniqueConstraint("journey_id", "step_id", name="uq_journey_step_progress"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journey_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("journey_instances.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[int] = mapped_column(Integer, ForeignKey("journey_template_steps.id"), index=True)
    status: Mapped[str] = mapped_column(String(64), default="pending")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reward_transaction_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("loyalty_transactions.id"), nullable=True
    )

    journey: Mapped[JourneyInstance] = relationship(back_populates="progress")
    step: Mapped[JourneyTemplateStep] = relationship()
