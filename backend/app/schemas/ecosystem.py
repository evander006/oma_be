"""Request schemas for the connected OMA home ecosystem MVP."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class PropertyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    address: str | None = Field(default=None, max_length=512)
    property_type: str | None = Field(default=None, max_length=128)
    tenure: Literal["owned", "rented"] | None = None


class RoomPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    room_type: str | None = Field(default=None, max_length=128)
    description: str | None = None
    width_m: Decimal | None = Field(default=None, gt=0)
    length_m: Decimal | None = Field(default=None, gt=0)
    height_m: Decimal | None = Field(default=None, gt=0)
    style_preference: str | None = Field(default=None, max_length=128)
    wall_material: str | None = Field(default=None, max_length=255)
    floor_material: str | None = Field(default=None, max_length=255)
    ceiling_material: str | None = Field(default=None, max_length=255)


class HomeEquipmentCreate(BaseModel):
    room_id: int | None = None
    product_id: str | None = None
    contractor_id: int | None = None
    name: str = Field(min_length=1, max_length=512)
    quantity: int = Field(default=1, ge=1, le=1000)
    status: str = Field(default="installed", max_length=64)
    specifications: dict[str, Any] = Field(default_factory=dict)
    installed_at: datetime | None = None
    notes: str | None = None


class WorkOrderCreate(BaseModel):
    contractor_id: int
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    property_id: int | None = None
    room_id: int | None = None
    project_id: int | None = None
    budget_byn: Decimal | None = Field(default=None, ge=0)
    shared_fields: list[str] = Field(default_factory=list)
    consent_granted: bool = False


class WorkOrderStatusPatch(BaseModel):
    status: Literal[
        "submitted",
        "accepted",
        "materials_proposed",
        "scheduled",
        "in_progress",
        "completed",
        "declined",
    ]


class MaterialProposalItemCreate(BaseModel):
    product_id: str
    quantity: int = Field(default=1, ge=1, le=1000)


class MaterialProposalCreate(BaseModel):
    items: list[MaterialProposalItemCreate] = Field(min_length=1)


class JourneyCreate(BaseModel):
    template_id: int
    project_id: int | None = None
    property_id: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
