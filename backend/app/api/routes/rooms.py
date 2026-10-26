from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_room_owner
from app.core.config import get_settings
from app.db.models import Property, Room, RoomPhoto, RoomPlacement, User
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
    placement = RoomPlacement(room_id=room.id, product_id=product_id)
    db.add(placement)
    db.commit()
    db.refresh(placement)
    return {"id": placement.id, "room_id": room.id, "product_id": product_id}
