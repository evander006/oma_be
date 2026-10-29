from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_room_owner
from app.core.config import get_settings
from app.db.models import Product, Property, Room, RoomDesignPlacement, RoomPhoto, RoomPlacement, User
from app.services.purchase_eligibility import eligible_order_products
from app.db.session import get_db
from app.schemas import (
    PropertyCreate,
    PropertyOut,
    RecommendationsResponse,
    RoomCreate,
    RoomOut,
    RoomPhotoOut,
)
from app.services.asset_urls import serialize_room_photo
from app.services.image_service import save_room_photo
from app.services.recommendation_service import recommend_from_room

router = APIRouter(tags=["rooms"])


class PlacementCreate(BaseModel):
    product_id: str = Field(min_length=1, max_length=64)
    pos_x: float = Field(default=0.0, ge=-50.0, le=50.0)
    pos_y: float = Field(default=0.06, ge=0.0, le=10.0)
    pos_z: float = Field(default=0.0, ge=-50.0, le=50.0)
    rotation_y: float = Field(default=0.0, ge=-1000.0, le=1000.0)


class PlacementPosition(BaseModel):
    pos_x: float = Field(ge=-50.0, le=50.0)
    pos_y: float = Field(default=0.06, ge=0.0, le=10.0)
    pos_z: float = Field(ge=-50.0, le=50.0)
    rotation_y: float = Field(default=0.0, ge=-1000.0, le=1000.0)



@router.post("/properties", response_model=PropertyOut)
def create_property(
    payload: PropertyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Property:
    prop = Property(
        user_id=user.id,
        name=payload.name,
        address=payload.address,
        property_type=payload.property_type,
        tenure=payload.tenure,
    )
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return prop


@router.get("/properties", response_model=list[PropertyOut])
def list_properties(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[Property]:
    return db.query(Property).filter(Property.user_id == user.id).all()


@router.get("/properties/{property_id}", response_model=PropertyOut)
def get_property(
    property_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Property:
    prop = (
        db.query(Property)
        .filter(Property.id == property_id, Property.user_id == user.id)
        .first()
    )
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


@router.delete("/properties/{property_id}")
def delete_property(
    property_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    prop = (
        db.query(Property)
        .filter(Property.id == property_id, Property.user_id == user.id)
        .first()
    )
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    db.delete(prop)
    db.commit()
    return {"deleted": True, "id": property_id}


@router.post("/rooms", response_model=RoomOut)
def create_room(
    payload: RoomCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Room:
    prop = (
        db.query(Property)
        .filter(Property.id == payload.property_id, Property.user_id == user.id)
        .first()
    )
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    room = Room(
        property_id=prop.id,
        name=payload.name,
        room_type=payload.room_type,
        description=payload.description,
        width_m=payload.width_m,
        length_m=payload.length_m,
        height_m=payload.height_m,
        style_preference=payload.style_preference,
        wall_material=payload.wall_material,
        floor_material=payload.floor_material,
        ceiling_material=payload.ceiling_material,
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


@router.get("/rooms", response_model=list[RoomOut])
def list_rooms(
    property_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Room]:
    q = (
        db.query(Room)
        .join(Property)
        .filter(Property.user_id == user.id)
    )
    if property_id is not None:
        q = q.filter(Room.property_id == property_id)
    return q.all()


@router.get("/rooms/{room_id}", response_model=RoomOut)
def get_room(
    room_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Room:
    return require_room_owner(db, room_id, user)


@router.post("/rooms/{room_id}/photos", response_model=RoomPhotoOut)
async def upload_room_photo(
    room_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RoomPhotoOut:
    room = require_room_owner(db, room_id, user)
    settings = get_settings()
    if len(room.photos) >= settings.max_room_photos:
        raise HTTPException(status_code=400, detail="Photo limit reached for room")
    rel, mime, width, height = await save_room_photo(room_id, file)
    photo = RoomPhoto(
        room_id=room.id,
        relative_path=rel,
        original_filename=file.filename,
        mime_type=mime,
        width=width,
        height=height,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return serialize_room_photo(photo)


@router.get("/rooms/{room_id}/photos", response_model=list[RoomPhotoOut])
def list_room_photos(
    room_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[RoomPhotoOut]:
    room = require_room_owner(db, room_id, user)
    return [serialize_room_photo(p) for p in room.photos]


@router.delete("/rooms/{room_id}/photos/{photo_id}")
def delete_room_photo(
    room_id: int,
    photo_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    room = require_room_owner(db, room_id, user)
    photo = (
        db.query(RoomPhoto)
        .filter(RoomPhoto.id == photo_id, RoomPhoto.room_id == room.id)
        .first()
    )
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    settings = get_settings()
    path = settings.uploads_dir / "rooms" / str(room.id) / Path(photo.relative_path).name
    db.delete(photo)
    db.commit()
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            pass
    return {"deleted": True, "id": photo_id}


@router.get("/rooms/{room_id}/recommendations", response_model=RecommendationsResponse)
def room_recommendations(
    room_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecommendationsResponse:
    room = require_room_owner(db, room_id, user)
    return recommend_from_room(
        db,
        room=room,
        prompt=f"Подбери товары для комнаты {room.name}",
        photo_ids=[],
        max_budget=user.budget_limit,
        preferred_style=room.style_preference or user.preferred_style,
        category_ids=[],
    )


@router.post("/rooms/{room_id}/placements")
def add_placement(
    room_id: int,
    product_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    room = require_room_owner(db, room_id, user)
    eligible = eligible_order_products(db, user)
    if product_id not in eligible:
        raise HTTPException(
            status_code=409,
            detail=(
                "Only products present in the user's completed OMA order "
                "or explicitly labelled demo order can be placed in the 3D home"
            ),
        )
    existing = (
        db.query(RoomPlacement)
        .filter(
            RoomPlacement.room_id == room.id,
            RoomPlacement.product_id == product_id,
        )
        .first()
    )
    if existing:
        return {
            "id": existing.id,
            "room_id": room.id,
            "product_id": product_id,
            "is_demo": eligible[product_id],
        }
    placement = RoomPlacement(room_id=room.id, product_id=product_id)
    db.add(placement)
    db.commit()
    db.refresh(placement)
    return {
        "id": placement.id,
        "room_id": room.id,
        "product_id": product_id,
        "is_demo": eligible[product_id],
    }



@router.patch("/rooms/{room_id}/placements/{placement_id}")
def update_owned_placement(
    room_id: int,
    placement_id: int,
    payload: PlacementPosition,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    room = require_room_owner(db, room_id, user)
    placement = (
        db.query(RoomPlacement)
        .filter(RoomPlacement.id == placement_id, RoomPlacement.room_id == room.id)
        .first()
    )
    if not placement:
        raise HTTPException(status_code=404, detail="Placement not found")
    placement.pos_x = payload.pos_x
    placement.pos_y = payload.pos_y
    placement.pos_z = payload.pos_z
    placement.rotation_y = payload.rotation_y
    db.commit()
    db.refresh(placement)
    return {
        "id": placement.id,
        "room_id": room.id,
        "product_id": placement.product_id,
        "placement_type": "owned",
        "is_demo": eligible_order_products(db, user).get(placement.product_id, False),
        "position": {
            "x": float(placement.pos_x or 0),
            "y": float(placement.pos_y or 0.06),
            "z": float(placement.pos_z or 0),
            "rotation_y": float(placement.rotation_y or 0),
        },
    }


@router.delete("/rooms/{room_id}/placements/{placement_id}")
def delete_owned_placement(
    room_id: int,
    placement_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    room = require_room_owner(db, room_id, user)
    placement = (
        db.query(RoomPlacement)
        .filter(RoomPlacement.id == placement_id, RoomPlacement.room_id == room.id)
        .first()
    )
    if not placement:
        raise HTTPException(status_code=404, detail="Placement not found")
    db.delete(placement)
    db.commit()
    return {"deleted": True, "id": placement_id, "placement_type": "owned"}


@router.post("/rooms/{room_id}/design-placements")
def add_design_placement(
    room_id: int,
    payload: PlacementCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Add one catalog instance; previews remain separate from owned purchases."""
    room = require_room_owner(db, room_id, user)
    product = db.get(Product, payload.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    eligible = eligible_order_products(db, user)
    if payload.product_id in eligible:
        owned = (
            db.query(RoomPlacement)
            .filter(
                RoomPlacement.room_id == room.id,
                RoomPlacement.product_id == payload.product_id,
            )
            .first()
        )
        # The first eligible instance is linked as owned. Further copies of the
        # same SKU are separate design previews so chairs, lamps, etc. can repeat.
        if not owned:
            owned = RoomPlacement(room_id=room.id, product_id=payload.product_id)
            owned.pos_x = payload.pos_x
            owned.pos_y = payload.pos_y
            owned.pos_z = payload.pos_z
            owned.rotation_y = payload.rotation_y
            db.add(owned)
            db.commit()
            db.refresh(owned)
            return {
                "id": owned.id,
                "room_id": room.id,
                "product_id": product.id,
                "name": product.name,
                "placement_type": "owned",
                "is_demo": eligible[payload.product_id],
            }

    # Every click creates a distinct instance. The same SKU can appear more than once.
    placement = RoomDesignPlacement(
        room_id=room.id,
        product_id=payload.product_id,
        pos_x=payload.pos_x,
        pos_y=payload.pos_y,
        pos_z=payload.pos_z,
        rotation_y=payload.rotation_y,
    )
    db.add(placement)
    db.commit()
    db.refresh(placement)
    return {
        "id": placement.id,
        "room_id": room.id,
        "product_id": product.id,
        "name": product.name,
        "placement_type": "preview",
        "is_preview": True,
        "purchase_status": "design_preview",
    }


@router.patch("/rooms/{room_id}/design-placements/{placement_id}")
def update_design_placement(
    room_id: int,
    placement_id: int,
    payload: PlacementPosition,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    room = require_room_owner(db, room_id, user)
    placement = (
        db.query(RoomDesignPlacement)
        .filter(
            RoomDesignPlacement.id == placement_id,
            RoomDesignPlacement.room_id == room.id,
        )
        .first()
    )
    if not placement:
        raise HTTPException(status_code=404, detail="Design placement not found")
    placement.pos_x = payload.pos_x
    placement.pos_y = payload.pos_y
    placement.pos_z = payload.pos_z
    placement.rotation_y = payload.rotation_y
    db.commit()
    db.refresh(placement)
    return {
        "id": placement.id,
        "room_id": room.id,
        "product_id": placement.product_id,
        "placement_type": "preview",
        "is_preview": True,
        "position": {
            "x": float(placement.pos_x or 0),
            "y": float(placement.pos_y or 0.06),
            "z": float(placement.pos_z or 0),
            "rotation_y": float(placement.rotation_y or 0),
        },
    }


@router.delete("/rooms/{room_id}/design-placements/{placement_id}")
def delete_design_placement(
    room_id: int,
    placement_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    room = require_room_owner(db, room_id, user)
    placement = (
        db.query(RoomDesignPlacement)
        .filter(
            RoomDesignPlacement.id == placement_id,
            RoomDesignPlacement.room_id == room.id,
        )
        .first()
    )
    if not placement:
        raise HTTPException(status_code=404, detail="Design placement not found")
    db.delete(placement)
    db.commit()
    return {"deleted": True, "id": placement_id, "placement_type": "preview"}
