from __future__ import annotations

import time
from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_room_owner
from app.core.config import get_settings
from app.db.models import User
from app.db.models.renovation import DesignVersion
from app.db.session import get_db
from app.schemas import (
    AIChatRequest,
    AIChatResponse,
    AIRecommendRequest,
    AnalyzeRoomRequest,
    BudgetSummary,
    DesignSessionCreate,
    DesignSessionGenerateRequest,
    RecommendationItem,
    RecommendationsResponse,
    RoomAnalysisOut,
    RoomRecommendRequest,
    StructuredRoomAnalysisOut,
)
from app.services.ai_capabilities import get_ai_capabilities
from app.services.ai_provider import AIProviderError
from app.services.asset_urls import serialize_product
from app.services.catalog_service import filter_candidates_for_ai
from app.services.design_service import (
    analyze_and_attach,
    create_design_session,
    create_version_with_products,
    enrich_version_products,
    generate_visualization,
    get_owned_session,
    replace_product_in_version,
    serialize_session,
)
from app.services.recommendation_service import (
    _apply_budget_filter,
    chat_with_assistant,
    recommend_from_room,
)
from app.services.room_analysis_service import analyze_room_photos

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


@router.get("/capabilities")
def ai_capabilities() -> dict:
    caps = get_ai_capabilities()
    settings = get_settings()
    return {
        "vision_language": {
            "provider": caps.provider_label,
            "model": caps.model_id,
            "supports_image_input": caps.supports_image_input,
            "supports_image_output": False,
        },
        "text_reasoning": {
            "provider": caps.provider_label,
            "model": caps.model_id,
        },
        "image_generation": {
            "provider": settings.image_gen_provider,
            "model": settings.image_gen_model,
            "supports_image_output": caps.supports_image_output,
            "max_product_refs": settings.image_gen_max_product_refs,
            "note": (
                "Configured VL model analyzes photos; it does not edit rooms with "
                "product reference images unless IMAGE_GEN_PROVIDER is a real edit endpoint."
            ),
        },
        "privacy": (
            "Room photos sent to the configured hosted AI provider leave this server "
            "and are processed under that provider's policies."
        ),
    }


@router.post("/chat", response_model=AIChatResponse)
def ai_chat(
    payload: AIChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AIChatResponse:
    _rate_limit(user.id)
    if payload.room_id:
        require_room_owner(db, payload.room_id, user)
    try:
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
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
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
    try:
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
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    candidates = filter_candidates_for_ai(
        db, budget=payload.budget, category_ids=payload.category_ids or None, limit=30
    )
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
        alternatives=[],
        warnings=[] if selected else ["Подходящих товаров не найдено"],
        missing_information=[],
    )


@router.post("/analyze-room", response_model=StructuredRoomAnalysisOut)
def analyze_room_structured(
    payload: AnalyzeRoomRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StructuredRoomAnalysisOut:
    """Structured multimodal room analysis (persisted)."""
    _rate_limit(user.id)
    room = require_room_owner(db, payload.room_id, user)
    if payload.width_m is not None:
        room.width_m = payload.width_m
    if payload.length_m is not None:
        room.length_m = payload.length_m
    if payload.height_m is not None:
        room.height_m = payload.height_m
    if payload.style:
        room.style_preference = payload.style
    if payload.room_type:
        room.room_type = payload.room_type
    db.commit()
    try:
        structured, row = analyze_room_photos(
            db,
            room=room,
            user_id=user.id,
            prompt=payload.prompt,
            photo_ids=payload.photo_ids or None,
            style=payload.style,
            budget=payload.budget,
            category_ids=payload.category_ids,
            keep_furniture=payload.keep_furniture,
            renovation_goals=payload.renovation_goals,
            user_room_type=payload.room_type or room.room_type,
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return StructuredRoomAnalysisOut(
        id=row.id,
        room_type=structured.room_type,
        room_type_confidence=structured.room_type_confidence,
        visible_furniture=structured.visible_furniture,
        dominant_colors=structured.dominant_colors,
        approximate_style=structured.approximate_style,
        lighting=structured.lighting,
        furnishing_opportunities=structured.furnishing_opportunities,
        constraints=structured.constraints,
        uncertainties=structured.uncertainties,
        questions=structured.questions,
        summary=structured.summary,
        provider=row.provider,
        model_id=row.model_id,
    )


@router.post("/recommendations/from-room", response_model=RecommendationsResponse)
def recommendations_from_room(
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
    try:
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
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/design-sessions")
def create_session(
    payload: DesignSessionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if payload.room_id is not None:
        require_room_owner(db, payload.room_id, user)
    session = create_design_session(
        db,
        user_id=user.id,
        room_id=payload.room_id,
        title=payload.title,
        style=payload.style,
        budget=payload.budget,
    )
    return serialize_session(session)


@router.get("/design-sessions/{session_id}")
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    session = get_owned_session(db, session_id, user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Design session not found")
    data = serialize_session(session)
    for v in data["versions"]:
        enrich_version_products(db, v)
    return data


@router.get("/design-sessions/{session_id}/versions")
def list_versions(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    session = get_owned_session(db, session_id, user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Design session not found")
    data = serialize_session(session)
    for v in data["versions"]:
        enrich_version_products(db, v)
    return data["versions"]


@router.post("/design-sessions/{session_id}/analyze")
def analyze_session_room(
    session_id: int,
    prompt: str = "Проанализируй комнату",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _rate_limit(user.id)
    session = get_owned_session(db, session_id, user.id)
    if not session or not session.room_id:
        raise HTTPException(status_code=400, detail="Session requires a room")
    room = require_room_owner(db, session.room_id, user)
    try:
        analyze_and_attach(db, session=session, room=room, user_id=user.id, prompt=prompt)
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return serialize_session(get_owned_session(db, session_id, user.id))


@router.post("/design-sessions/{session_id}/generate")
def generate_design(
    session_id: int,
    payload: DesignSessionGenerateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Create a design version and attempt image generation (may be unavailable)."""
    _rate_limit(user.id)
    session = get_owned_session(db, session_id, user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Design session not found")

    room = None
    if session.room_id:
        room = require_room_owner(db, session.room_id, user)

    version: DesignVersion | None = None
    if payload.replace_product_id and payload.with_new_product_id and session.versions:
        version = max(session.versions, key=lambda v: v.version_number)
        try:
            replace_product_in_version(
                db,
                version=version,
                old_product_id=payload.replace_product_id,
                new_product_id=payload.with_new_product_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # Reload
        session = get_owned_session(db, session_id, user.id)
        version = max(session.versions, key=lambda v: v.version_number)
    else:
        if not payload.product_ids:
            raise HTTPException(status_code=400, detail="product_ids required")
        version = create_version_with_products(
            db,
            session=session,
            product_ids=payload.product_ids,
            instructions=payload.instructions,
            photo_ids=payload.photo_ids,
        )

    viz = generate_visualization(
        db,
        session=session,
        version=version,
        room=room,
        idempotency_key=payload.idempotency_key,
    )
    session = get_owned_session(db, session_id, user.id)
    data = serialize_session(session)
    for v in data["versions"]:
        enrich_version_products(db, v)

    # Product subtotal calculated in Python
    subtotal = Decimal("0")
    for v in data["versions"]:
        if v["id"] == version.id:
            for sp in v.get("selected_products") or []:
                prod = sp.get("product") or {}
                price = prod.get("price")
                if price is not None:
                    subtotal += Decimal(str(price))

    return {
        "session": data,
        "version_id": version.id,
        "visualization": {
            "id": viz.id,
            "status": viz.status,
            "error_message": viz.error_message,
            "disclaimer": viz.disclaimer,
        },
        "product_subtotal": subtotal,
        "generation_status": version.generation_status,
        "retry_allowed": version.generation_status in {"failed", "unavailable", "pending"},
    }
