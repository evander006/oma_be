"""Image validation, resizing, and safe storage."""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings

ALLOWED_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


async def save_room_photo(room_id: int, upload: UploadFile) -> tuple[str, str, int, int]:
    settings = get_settings()
    data = await upload.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large (max {settings.max_upload_bytes} bytes)",
        )
    content_type = (upload.content_type or "").lower()
    if content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="Unsupported image MIME type")
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            fmt = (img.format or "JPEG").upper()
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail="Invalid image content") from exc

    ext = ALLOWED_MIME[content_type]
    if fmt == "PNG":
        ext = ".png"
    elif fmt == "WEBP":
        ext = ".webp"
    else:
        ext = ".jpg"

    safe_name = f"{uuid.uuid4().hex}{ext}"
    dest_dir = settings.uploads_dir / "rooms" / str(room_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / safe_name
    # Re-encode to strip untrusted metadata / odd containers.
    with Image.open(io.BytesIO(data)) as img:
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        save_kwargs = {}
        if ext == ".jpg":
            if img.mode == "RGBA":
                img = img.convert("RGB")
            save_kwargs["quality"] = 85
        img.save(dest, **save_kwargs)
    rel = f"uploads/rooms/{room_id}/{safe_name}"
    return rel, content_type, width, height


def load_resized_image_bytes(path: Path, max_side: int = 1280) -> tuple[bytes, str]:
    with Image.open(path) as img:
        img = img.convert("RGB")
        w, h = img.size
        scale = min(1.0, max_side / max(w, h))
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return buf.getvalue(), "image/jpeg"
