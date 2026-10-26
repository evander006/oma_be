from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_room_owner
from app.core.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.schemas import (
    AIChatRequest,
    AIChatResponse,
    AIRecommendRequest,
    RecommendationsResponse,
    RoomRecommendRequest,
)
from app.services.asset_urls import serialize_product
from app.services.catalog_service import filter_candidates_for_ai
from app.services.recommendation_service import chat_with_assistant, recommend_from_room
from app.schemas import BudgetSummary, RecommendationItem, RoomAnalysisOut

router = APIRouter(prefix="/ai", tags=["ai"])

_rate_buckets: dict[int, list[float]] = defaultdict(list)


def _rate_limit(user_id: int) -> None:
    settings = get_settings()
    now = time.time()
    window = [t for t in _rate_buckets[user_id] if now - t < 60]
    if len(window) >= settings.rate_limit_ai_per_minute:
        raise HTTPException(status_code=429, detail="AI rate limit exceeded")
    window.append(now)
    _rate_buckets[user_id] = window


@router.post("/chat", response_model=AIChatResponse)
def ai_chat(
    payload: AIChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AIChatResponse:
    _rate_limit(user.id)
    if payload.room_id:
        require_room_owner(db, payload.room_id, user)
    session, reply, product_ids, analysis = chat_with_assistant(
        db,
        user_id=user.id,
        message=payload.message,
        session_id=payload.session_id,
        room_id=payload.room_id,
        photo_ids=payload.photo_ids,
        budget=payload.budget,
        style=payload.style,
    )
    return AIChatResponse(
        session_id=session.id,
        reply=reply,
        product_ids=product_ids,
        analysis=analysis,
    )


@router.post("/recommendations", response_model=RecommendationsResponse)
def ai_recommendations(
    payload: AIRecommendRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecommendationsResponse:
    _rate_limit(user.id)
    if payload.room_id:
        room = require_room_owner(db, payload.room_id, user)
        return recommend_from_room(
            db,
            room=room,
            prompt=payload.prompt,
            photo_ids=[],
            max_budget=payload.budget,
            preferred_style=payload.style,
            category_ids=payload.category_ids,
            limit=payload.limit,
        )
    from app.services.recommendation_service import _apply_budget_filter

    candidates = filter_candidates_for_ai(
        db, budget=payload.budget, category_ids=payload.category_ids or None, limit=30
    )
    # Per-item filter already applied; also enforce total budget for the set.
    selected = _apply_budget_filter(candidates, payload.budget)[: payload.limit]
    total = sum((p.price or 0) for p in selected)
    return RecommendationsResponse(
        room_analysis=RoomAnalysisOut(
            summary="Текстовые рекомендации без комнаты.",
            observations=[payload.prompt],
            assumptions=[],
            uncertainties=[],
            missing_info=[],
        ),
        recommendations=[
            RecommendationItem(
                product_id=p.id,
                reason="Соответствует поисковому запросу и серверным фильтрам.",
                product=serialize_product(p),
            )
            for p in selected
        ],
        budget=BudgetSummary(
            max_budget=payload.budget,
            recommended_total=total,
            within_budget=None if payload.budget is None else total <= payload.budget,
            remaining=None if payload.budget is None else payload.budget - total,
        ),
        explanation="Каталог отфильтрован на сервере.",
    )


@router.post("/analyze-room", response_model=RecommendationsResponse)
def analyze_room(
    payload: RoomRecommendRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecommendationsResponse:
    _rate_limit(user.id)
    room = require_room_owner(db, payload.room_id, user)
    if payload.width_m is not None:
        room.width_m = payload.width_m
    if payload.length_m is not None:
        room.length_m = payload.length_m
    if payload.height_m is not None:
        room.height_m = payload.height_m
    if payload.preferred_style:
        room.style_preference = payload.preferred_style
    db.commit()
    return recommend_from_room(
        db,
        room=room,
        prompt=payload.prompt or "Проанализируй комнату по фото",
        photo_ids=payload.photo_ids,
        max_budget=payload.max_budget,
        preferred_style=payload.preferred_style,
        category_ids=payload.category_ids,
        limit=payload.limit,
    )


@router.post("/recommendations/from-room", response_model=RecommendationsResponse)
def recommendations_from_room(
    payload: RoomRecommendRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecommendationsResponse:
    return analyze_room(payload, db, user)
