"""Pydantic API schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(APIModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class HealthResponse(APIModel):
    status: str
    version: str
    environment: str
    ai_provider: str
    gemini_model: str
    demo_user: str = "Анна"


class UserOut(APIModel):
    id: int
    email: str
    display_name: str
    is_demo: bool
    preferred_style: Optional[str] = None
    budget_limit: Optional[Decimal] = None


class CategoryOut(APIModel):
    id: str
    name: str
    slug: str
    parent_id: Optional[str] = None
    source_url: Optional[str] = None


class ProductImageOut(APIModel):
    id: int
    url: str
    sort_order: int
    is_primary: bool
    width: Optional[int] = None
    height: Optional[int] = None


class ProductSpecOut(APIModel):
    name: str
    value: str
    unit: Optional[str] = None


class Product3DOut(APIModel):
    product_id: str
    has_3d_model: bool
    url: Optional[str] = None
    format: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    limitations: Optional[str] = None
    width: Optional[Decimal] = None
    height: Optional[Decimal] = None
    depth: Optional[Decimal] = None
    units: str = "m"


class ProductOut(APIModel):
    id: str
    source_product_id: Optional[str] = None
    sku: Optional[str] = None
    name: str
    brand: Optional[str] = None
    category_id: Optional[str] = None
    subcategory: Optional[str] = None
    source_url: str
    description: Optional[str] = None
    price: Optional[Decimal] = None
    currency: str
    price_retrieved_at: Optional[datetime] = None
    availability: Optional[str] = None
    width_mm: Optional[Decimal] = None
    height_mm: Optional[Decimal] = None
    depth_mm: Optional[Decimal] = None
    diameter_mm: Optional[Decimal] = None
    weight_kg: Optional[Decimal] = None
    materials: Optional[str] = None
    colors: Optional[str] = None
    validation_status: str
    has_3d_model: bool
    primary_image_url: Optional[str] = None
    images: list[ProductImageOut] = Field(default_factory=list)
    specifications: list[ProductSpecOut] = Field(default_factory=list)
    model_3d: Optional[Product3DOut] = None


class PropertyCreate(APIModel):
    name: str
    address: Optional[str] = None
    property_type: Optional[str] = None


class PropertyOut(APIModel):
    id: int
    user_id: int
    name: str
    address: Optional[str] = None
    property_type: Optional[str] = None


class RoomCreate(APIModel):
    property_id: int
    name: str
    room_type: Optional[str] = None
    description: Optional[str] = None
    width_m: Optional[Decimal] = None
    length_m: Optional[Decimal] = None
    height_m: Optional[Decimal] = None
    style_preference: Optional[str] = None


class RoomOut(APIModel):
    id: int
    property_id: int
    name: str
    room_type: Optional[str] = None
    description: Optional[str] = None
    width_m: Optional[Decimal] = None
    length_m: Optional[Decimal] = None
    height_m: Optional[Decimal] = None
    style_preference: Optional[str] = None


class RoomPhotoOut(APIModel):
    id: int
    room_id: int
    url: str
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class FavoriteOut(APIModel):
    id: int
    product_id: str
    product: Optional[ProductOut] = None


class CartItemOut(APIModel):
    id: int
    product_id: str
    quantity: int
    product: Optional[ProductOut] = None


class CartOut(APIModel):
    id: int
    currency: str
    items: list[CartItemOut] = Field(default_factory=list)
    total: Decimal = Decimal("0")


class CartItemCreate(APIModel):
    product_id: str
    quantity: int = 1


class InstallationServiceOut(APIModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    price: Decimal
    currency: str
    estimated_hours: Optional[Decimal] = None


class OrderCreate(APIModel):
    product_ids: list[str] = Field(default_factory=list)
    installation_service_id: Optional[int] = None
    notes: Optional[str] = None
    from_cart: bool = True


class OrderItemOut(APIModel):
    id: int
    product_id: str
    quantity: int
    unit_price: Optional[Decimal] = None
    currency: str


class OrderOut(APIModel):
    id: int
    status: str
    currency: str
    total_amount: Decimal
    is_demonstration: bool
    notes: Optional[str] = None
    items: list[OrderItemOut] = Field(default_factory=list)


class ChatMessageOut(APIModel):
    id: int
    role: str
    content: str
    meta: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None


class ChatSessionOut(APIModel):
    id: int
    room_id: Optional[int] = None
    title: Optional[str] = None
    messages: list[ChatMessageOut] = Field(default_factory=list)


class AIChatRequest(APIModel):
    message: str
    session_id: Optional[int] = None
    room_id: Optional[int] = None
    photo_ids: list[int] = Field(default_factory=list)
    budget: Optional[Decimal] = None
    style: Optional[str] = None


class AIChatResponse(APIModel):
    session_id: int
    reply: str
    product_ids: list[str] = Field(default_factory=list)
    analysis: Optional[dict[str, Any]] = None


class AIRecommendRequest(APIModel):
    prompt: str
    budget: Optional[Decimal] = None
    style: Optional[str] = None
    category_ids: list[str] = Field(default_factory=list)
    room_id: Optional[int] = None
    limit: int = 5


class RoomRecommendRequest(APIModel):
    room_id: int
    prompt: str = ""
    photo_ids: list[int] = Field(default_factory=list)
    max_budget: Optional[Decimal] = None
    preferred_style: Optional[str] = None
    category_ids: list[str] = Field(default_factory=list)
    width_m: Optional[Decimal] = None
    length_m: Optional[Decimal] = None
    height_m: Optional[Decimal] = None
    limit: int = 6


class RecommendationItem(APIModel):
    product_id: str
    reason: str
    product: Optional[ProductOut] = None


class BudgetSummary(APIModel):
    max_budget: Optional[Decimal] = None
    recommended_total: Decimal = Decimal("0")
    currency: str = "BYN"
    within_budget: Optional[bool] = None
    remaining: Optional[Decimal] = None


class RoomAnalysisOut(APIModel):
    summary: str
    observations: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)


class RecommendationsResponse(APIModel):
    room_analysis: Optional[RoomAnalysisOut] = None
    recommendations: list[RecommendationItem] = Field(default_factory=list)
    budget: BudgetSummary
    explanation: str = ""
