"""Multimodal room analysis with Pydantic validation and persistence."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Room, RoomPhoto
from app.db.models.renovation import RoomAnalysis
from app.services.ai_capabilities import VisionAnalysisResult, get_ai_capabilities
from app.services.ai_provider import AIImagePart
from app.services.image_service import load_resized_image_bytes


class StructuredRoomAnalysis(BaseModel):
    room_type: str | None = None
    room_type_confidence: float | None = None
    visible_furniture: list[str] = Field(default_factory=list)
    dominant_colors: list[str] = Field(default_factory=list)
    approximate_style: str | None = None
    lighting: list[str] = Field(default_factory=list)
    furnishing_opportunities: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    summary: str = ""

    @field_validator("room_type_confidence")
    @classmethod
    def _clamp_confidence(cls, v: float | None) -> float | None:
        if v is None:
            return None
        return max(0.0, min(1.0, float(v)))


def _photo_path(room_id: int, photo: RoomPhoto) -> Path:
    settings = get_settings()
    name = Path(photo.relative_path).name
    return settings.uploads_dir / "rooms" / str(room_id) / name


def load_room_images(
    room: Room, photo_ids: list[int] | None = None
) -> list[AIImagePart]:
    settings = get_settings()
    images: list[AIImagePart] = []
    for photo in room.photos:
        if photo_ids and photo.id not in photo_ids:
            continue
        path = _photo_path(room.id, photo)
        if not path.is_file():
            continue
        data, mime = load_resized_image_bytes(path)
        images.append(AIImagePart(mime_type=mime, data=data))
        if len(images) >= settings.max_room_photos:
            break
    return images


def _validate_or_retry(raw: VisionAnalysisResult) -> StructuredRoomAnalysis:
    payload = {
        "room_type": raw.room_type,
        "room_type_confidence": raw.room_type_confidence,
        "visible_furniture": raw.visible_furniture,
        "dominant_colors": raw.dominant_colors,
        "approximate_style": raw.approximate_style,
        "lighting": raw.lighting,
        "furnishing_opportunities": raw.furnishing_opportunities,
        "constraints": raw.constraints,
        "uncertainties": raw.uncertainties,
        "questions": raw.questions,
        "summary": raw.summary,
    }
    try:
        return StructuredRoomAnalysis.model_validate(payload)
    except ValidationError:
        return StructuredRoomAnalysis(
            summary=raw.summary or "Частичный анализ (валидация смягчена).",
            uncertainties=list(raw.uncertainties)
            + ["Структура ответа модели частично невалидна"],
            questions=list(raw.questions) or ["Уточните тип комнаты и размеры"],
            visible_furniture=list(raw.visible_furniture),
            dominant_colors=list(raw.dominant_colors),
            lighting=list(raw.lighting),
            furnishing_opportunities=list(raw.furnishing_opportunities),
            constraints=list(raw.constraints),
            approximate_style=raw.approximate_style,
            room_type=raw.room_type if isinstance(raw.room_type, str) else None,
        )


def analyze_room_photos(
    db: Session,
    *,
    room: Room,
    user_id: int,
    prompt: str,
    photo_ids: list[int] | None = None,
    style: str | None = None,
    budget: Decimal | None = None,
    category_ids: list[str] | None = None,
    keep_furniture: list[str] | None = None,
    renovation_goals: str | None = None,
    user_room_type: str | None = None,
) -> tuple[StructuredRoomAnalysis, RoomAnalysis]:
    images = load_room_images(room, photo_ids)
    context: dict[str, Any] = {
        "room_name": room.name,
        "declared_room_type": user_room_type or room.room_type,
        "width_m": float(room.width_m) if room.width_m is not None else None,
        "length_m": float(room.length_m) if room.length_m is not None else None,
        "height_m": float(room.height_m) if room.height_m is not None else None,
        "style": style or room.style_preference,
        "budget": float(budget) if budget is not None else None,
        "category_ids": category_ids or [],
        "keep_furniture": keep_furniture or [],
        "renovation_goals": renovation_goals,
        "note": "Не выводите точные размеры из фото. При конфликте фото и текста — uncertainty.",
    }
    caps = get_ai_capabilities()
    raw = caps.vision.analyze_room(
        images=images,
        user_prompt=prompt or "Проанализируй комнату по фото",
        context=context,
    )
    # Conflict: user-declared type vs model
    declared = (user_room_type or room.room_type or "").strip().lower()
    detected = (raw.room_type or "").strip().lower()
    if declared and detected and declared != detected and declared not in detected:
        raw.uncertainties = list(raw.uncertainties) + [
            f"Пользователь указал тип «{declared}», по фото модель видит «{detected}»."
        ]
        raw.questions = list(raw.questions) + [
            "Подтвердите тип комнаты — фото и описание расходятся."
        ]

    structured = _validate_or_retry(raw)
    result_payload = structured.model_dump()
    result_payload["provider"] = raw.provider
    result_payload["model_id"] = raw.model_id
    result_payload["photo_count"] = len(images)

    row = RoomAnalysis(
        room_id=room.id,
        user_id=user_id,
        prompt=prompt,
        result_json=json.dumps(result_payload, ensure_ascii=False),
        provider=raw.provider,
        model_id=raw.model_id,
        status="completed",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return structured, row
