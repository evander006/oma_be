from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_room_owner
from app.db.models import User
from app.db.session import get_db
from app.services.asset_urls import (
    resolve_product_image_path,
    resolve_product_model_path,
    resolve_room_photo_path,
)

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/products/{product_id}/images/{filename}")
def serve_product_image(product_id: str, filename: str) -> FileResponse:
    path = resolve_product_image_path(product_id, filename)
    if not path:
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path)


@router.get("/products/{product_id}/model.glb")
def serve_product_model(product_id: str) -> FileResponse:
    path = resolve_product_model_path(product_id)
    if not path:
        raise HTTPException(status_code=404, detail="Model not found")
    return FileResponse(path, media_type="model/gltf-binary")


@router.get("/rooms/{room_id}/{filename}")
def serve_room_photo(
    room_id: int,
    filename: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    require_room_owner(db, room_id, user)
    path = resolve_room_photo_path(room_id, filename)
    if not path:
        raise HTTPException(status_code=404, detail="Photo not found")
    return FileResponse(path)
