"""The owned home scene: architectural rooms + explicitly eligible placements."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import Product, Property, Room, RoomDesignPlacement, RoomPlacement, User
from app.db.session import get_db
from app.services.asset_urls import product_model_url
from app.services.purchase_eligibility import eligible_order_products


router = APIRouter(tags=["scene"])


def _owned_property(db: Session, property_id: int, user: User) -> Property:
    prop = (
        db.query(Property)
        .filter(Property.id == property_id, Property.user_id == user.id)
        .first()
    )
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


def _float(value):
    return float(value) if value is not None else None


@router.get("/properties/{property_id}/scene")
def property_scene(
    property_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    prop = _owned_property(db, property_id, user)
    eligible = eligible_order_products(db, user)
    rooms = db.query(Room).filter(Room.property_id == prop.id).order_by(Room.id).all()
    placements = (
        db.query(RoomPlacement, Product)
        .join(Room, Room.id == RoomPlacement.room_id)
        .join(Product, Product.id == RoomPlacement.product_id)
        .filter(Room.property_id == prop.id)
        .all()
    )
    by_room: dict[int, list[dict]] = {room.id: [] for room in rooms}
    design_by_room: dict[int, list[dict]] = {room.id: [] for room in rooms}
    design_rows = (
        db.query(RoomDesignPlacement, Product)
        .join(Room, Room.id == RoomDesignPlacement.room_id)
        .join(Product, Product.id == RoomDesignPlacement.product_id)
        .filter(Room.property_id == prop.id)
        .all()
    )
    for placement, product in design_rows:
        # A design draft is not a second copy of a product already eligible as owned.
        if product.id in eligible:
            continue
        design_by_room[placement.room_id].append(
            {
                "placement_id": placement.id,
                "product_id": product.id,
                "name": product.name,
                "is_preview": True,
                "is_demo": False,
                "purchase_status": "design_preview",
                "category_id": product.category_id,
                "price": _float(product.price),
                "currency": product.currency or "BYN",
                "position": {
                    "x": _float(placement.pos_x),
                    "y": _float(placement.pos_y),
                    "z": _float(placement.pos_z),
                    "rotation_y": _float(placement.rotation_y),
                },
                "model_url": product_model_url(product.id)
                if product.has_3d_model and product.model_path else None,
                "model_source": product.model_source,
                "model_limitations": product.model_limitations,
                "dimensions_m": {
                    "width": _float(product.model_width_m),
                    "height": _float(product.model_height_m),
                    "depth": _float(product.model_depth_m),
                },
            }
        )
    for placement, product in placements:
        if placement.product_id not in eligible:
            continue
        by_room[placement.room_id].append(
            {
                "placement_id": placement.id,
                "product_id": product.id,
                "name": product.name,
                "is_demo": eligible[product.id],
                "is_preview": False,
                "placement_type": "owned",
                "category_id": product.category_id,
                "price": _float(product.price),
                "currency": product.currency or "BYN",
                "purchase_status": (
                    "demonstration_order" if eligible[product.id] else "confirmed_order"
                ),
                "position": {
                    "x": _float(placement.pos_x),
                    "y": _float(placement.pos_y),
                    "z": _float(placement.pos_z),
                    "rotation_y": _float(placement.rotation_y),
                },
                # Procedural GLB is not an exact manufacturer model.
                "model_url": product_model_url(product.id)
                if product.has_3d_model and product.model_path else None,
                "model_source": product.model_source,
                "model_limitations": product.model_limitations,
                "dimensions_m": {
                    "width": _float(product.model_width_m),
                    "height": _float(product.model_height_m),
                    "depth": _float(product.model_depth_m),
                },
            }
        )
    return {
        "property_id": prop.id,
        "name": prop.name,
        "is_demo_environment": bool(user.is_demo),
        "rooms": [
            {
                "id": room.id,
                "name": room.name,
                "room_type": room.room_type,
                "width_m": _float(room.width_m),
                "length_m": _float(room.length_m),
                "height_m": _float(room.height_m),
                "dimensions_confirmed": (
                    room.width_m is not None
                    and room.length_m is not None
                    and room.height_m is not None
                ),
                "products": by_room[room.id],
                "design_products": design_by_room[room.id],
            }
            for room in rooms
        ],
    }


@router.get("/scene/view/{property_id}", response_class=HTMLResponse, include_in_schema=False)
def scene_view(
    property_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HTMLResponse:
    _owned_property(db, property_id, user)
    html = (Path(__file__).resolve().parents[2] / "static" / "scene.html").read_text(
        encoding="utf-8"
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
