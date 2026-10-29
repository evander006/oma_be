"""ORM models aligned with the OMA. Дом Flutter domain."""
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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="Анна")
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    preferred_style: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    budget_limit: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)

    properties: Mapped[list["Property"]] = relationship(back_populates="user")
    favorites: Mapped[list["Favorite"]] = relationship(back_populates="user")
    carts: Mapped[list["Cart"]] = relationship(back_populates="user")
    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    chat_sessions: Mapped[list["ChatSession"]] = relationship(back_populates="user")


class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("categories.id"), nullable=True
    )
    source_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    parent: Mapped[Optional["Category"]] = relationship(remote_side=[id])
    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_product_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    sku: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    brand: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    category_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("categories.id"), nullable=True
    )
    subcategory: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="BYN")
    price_retrieved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    availability: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    width_mm: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    height_mm: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    depth_mm: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    diameter_mm: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    materials: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    colors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    style_tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # comma-separated
    room_types: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # comma-separated
    installation_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    installation_compatible: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(64), default="validated")
    source: Mapped[str] = mapped_column(String(64), default="oma.by")
    retrieved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    has_3d_model: Mapped[bool] = mapped_column(Boolean, default=False)
    model_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    model_format: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    model_source: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    model_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    model_limitations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_width_m: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    model_height_m: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    model_depth_m: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    model_units: Mapped[str] = mapped_column(String(16), default="m")

    category: Mapped[Optional[Category]] = relationship(back_populates="products")
    images: Mapped[list["ProductImage"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    specifications: Mapped[list["ProductSpecification"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class ProductImage(Base, TimestampMixin):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(String(64), ForeignKey("products.id"), index=True)
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    product: Mapped[Product] = relationship(back_populates="images")


class ProductSpecification(Base, TimestampMixin):
    __tablename__ = "product_specifications"
    __table_args__ = (UniqueConstraint("product_id", "name", name="uq_product_spec_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(String(64), ForeignKey("products.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    product: Mapped[Product] = relationship(back_populates="specifications")


class Property(Base, TimestampMixin):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    property_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    tenure: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    user: Mapped[User] = relationship(back_populates="properties")
    rooms: Mapped[list["Room"]] = relationship(
        back_populates="property", cascade="all, delete-orphan"
    )


class Room(Base, TimestampMixin):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(Integer, ForeignKey("properties.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    room_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    width_m: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    length_m: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    height_m: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    style_preference: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    wall_material: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    floor_material: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ceiling_material: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    property: Mapped[Property] = relationship(back_populates="rooms")
    photos: Mapped[list["RoomPhoto"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )
    placements: Mapped[list["RoomPlacement"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )
    design_placements: Mapped[list["RoomDesignPlacement"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )


class RoomPhoto(Base, TimestampMixin):
    __tablename__ = "room_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(Integer, ForeignKey("rooms.id"), index=True)
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    room: Mapped[Room] = relationship(back_populates="photos")


class RoomPlacement(Base, TimestampMixin):
    __tablename__ = "room_placements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(Integer, ForeignKey("rooms.id"), index=True)
    product_id: Mapped[str] = mapped_column(String(64), ForeignKey("products.id"), index=True)
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pos_x: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    pos_y: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    pos_z: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    rotation_y: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)

    room: Mapped[Room] = relationship(back_populates="placements")
    product: Mapped[Product] = relationship()


class RoomDesignPlacement(Base, TimestampMixin):
    """Unpurchased catalog products placed in a saved interior-design draft."""

    __tablename__ = "room_design_placements"
    __table_args__ = (
        UniqueConstraint("room_id", "product_id", name="uq_room_design_product"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(Integer, ForeignKey("rooms.id"), index=True)
    product_id: Mapped[str] = mapped_column(String(64), ForeignKey("products.id"), index=True)
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pos_x: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    pos_y: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    pos_z: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    rotation_y: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)

    room: Mapped[Room] = relationship(back_populates="design_placements")
    product: Mapped[Product] = relationship()


class Favorite(Base, TimestampMixin):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_favorite"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    product_id: Mapped[str] = mapped_column(String(64), ForeignKey("products.id"), index=True)

    user: Mapped[User] = relationship(back_populates="favorites")
    product: Mapped[Product] = relationship()


class Cart(Base, TimestampMixin):
    __tablename__ = "carts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True)
    currency: Mapped[str] = mapped_column(String(8), default="BYN")

    user: Mapped[User] = relationship(back_populates="carts")
    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart", cascade="all, delete-orphan"
    )


class CartItem(Base, TimestampMixin):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("cart_id", "product_id", name="uq_cart_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cart_id: Mapped[int] = mapped_column(Integer, ForeignKey("carts.id"), index=True)
    product_id: Mapped[str] = mapped_column(String(64), ForeignKey("products.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    cart: Mapped[Cart] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class InstallationService(Base, TimestampMixin):
    __tablename__ = "installation_services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="BYN")
    estimated_hours: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(64), default="demo_created")
    currency: Mapped[str] = mapped_column(String(8), default="BYN")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    installation_service_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("installation_services.id"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_demonstration: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    installation_service: Mapped[Optional[InstallationService]] = relationship()


class OrderItem(Base, TimestampMixin):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("orders.id"), index=True)
    product_id: Mapped[str] = mapped_column(String(64), ForeignKey("products.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="BYN")

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    room_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("rooms.id"), nullable=True
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    user: Mapped[User] = relationship(back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional JSON payload summary (product ids, analysis) — never raw image bytes.
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    session: Mapped[ChatSession] = relationship(back_populates="messages")


# Renovation / design / loyalty domain (imported for metadata registration).
from app.db.models.renovation import (  # noqa: E402
    DesignSession,
    DesignVersion,
    Estimate,
    EstimateLine,
    GeneratedVisualization,
    InstallationRequest,
    LoyaltyAccount,
    LoyaltyTransaction,
    RenovationProject,
    RenovationRequest,
    RenovationService,
    RenovationWorkItem,
    RoomAnalysis,
    SelectedDesignProduct,
)

# Digital-home ecosystem domain (imported for metadata registration).
from app.db.models.ecosystem import (  # noqa: E402
    ContractorFavorite,
    ContractorPortfolioItem,
    ContractorProfile,
    ContractorSpecialty,
    HomeEquipment,
    HomeHistoryEvent,
    JourneyInstance,
    JourneyStepProgress,
    JourneyTemplate,
    JourneyTemplateStep,
    MaterialProposal,
    MaterialProposalItem,
    WorkOrder,
)
