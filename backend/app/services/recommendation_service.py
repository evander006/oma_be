"""Catalog-grounded AI recommendations with server-side budget enforcement."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import ChatMessage, ChatSession, Product, Room
from app.schemas import (
    BudgetSummary,
    RecommendationItem,
    RecommendationsResponse,
    RoomAnalysisOut,
)
from app.services.ai_provider import AIImagePart, get_ai_provider
from app.services.asset_urls import serialize_product
from app.services.catalog_service import filter_candidates_for_ai, get_product
from app.services.image_service import load_resized_image_bytes


SYSTEM_PROMPT = """Ты — ассистент OMA. Дом для подбора товаров. Отвечай по-русски.
Твоя задача — подобрать товары из CATALOG_JSON под запрос пользователя.
Используй ТОЛЬКО id из каталога. Не выдумывай товары, цены и наличие.
В summary напиши короткий ответ человеку: что подобрал и почему (1–3 предложения).
В ranked_product_ids верни 1–5 лучших id из каталога по смыслу запроса.
Если точного совпадения нет (например «диван», а в каталоге только стеллажи/полки) —
честно скажи это в summary и предложи ближайшие позиции из каталога.
Отличай наблюдения по фото от предположений. Не утверждай точные размеры комнаты по фото.
Верни ТОЛЬКО JSON:
{
  "summary": "...",
  "observations": ["..."],
  "assumptions": ["..."],
  "uncertainties": ["..."],
  "missing_info": ["..."],
  "ranked_product_ids": ["id1", "id2"],
  "reasons": {"id1": "почему подходит"}
}
"""


_KEYWORD_CATEGORY_HINTS: list[tuple[tuple[str, ...], list[str]]] = [
    (("диван", "кресл", "мебел", "стол", "стул", "шкаф", "стеллаж", "полк", "комод"), ["furniture"]),
    (("ламп", "свет", "люстр", "бра", "светильн", "ночник", "освещ"), ["lighting", "lighting-ceiling"]),
    (("смесит", "кран", "сантех"), ["plumbing-faucets"]),
    (("раковин", "умывальн", "мойк"), ["plumbing-sinks", "kitchen-sinks"]),
    (("ванн",), ["bath"]),
]


def _category_hints_from_text(text: str) -> list[str]:
    low = text.lower()
    cats: list[str] = []
    for keys, ids in _KEYWORD_CATEGORY_HINTS:
        if any(k in low for k in keys):
            cats.extend(ids)
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for c in cats:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _keyword_rank(products: list[Product], query: str, limit: int = 5) -> list[Product]:
    tokens = [t for t in query.lower().replace(",", " ").split() if len(t) > 2]
    if not tokens:
        return products[:limit]
    scored: list[tuple[int, Product]] = []
    for p in products:
        blob = f"{p.name} {p.description or ''} {p.category_id or ''} {p.subcategory or ''}".lower()
        score = sum(1 for t in tokens if t in blob)
        if score:
            scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], x[1].price or Decimal("0")))
    return [p for _, p in scored[:limit]] or products[:limit]


def _catalog_payload(products: list[Product]) -> list[dict[str, Any]]:
    out = []
    for p in products:
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "brand": p.brand,
                "category_id": p.category_id,
                "price": float(p.price) if p.price is not None else None,
                "currency": p.currency,
                "width_mm": float(p.width_mm) if p.width_mm is not None else None,
                "height_mm": float(p.height_mm) if p.height_mm is not None else None,
                "depth_mm": float(p.depth_mm) if p.depth_mm is not None else None,
                "materials": p.materials,
                "colors": p.colors,
                "description": (p.description or "")[:400],
            }
        )
    return out


def _budget_summary(products: list[Product], max_budget: Decimal | None) -> BudgetSummary:
    settings = get_settings()
    total = sum((p.price or Decimal("0")) for p in products)
    within = None if max_budget is None else total <= max_budget
    remaining = None if max_budget is None else max_budget - total
    return BudgetSummary(
        max_budget=max_budget,
        recommended_total=total,
        currency=settings.default_currency,
        within_budget=within,
        remaining=remaining,
    )


def _apply_budget_filter(
    products: list[Product], max_budget: Decimal | None
) -> list[Product]:
    if max_budget is None:
        return products
    selected: list[Product] = []
    running = Decimal("0")
    for p in products:
        price = p.price if p.price is not None else Decimal("0")
        if running + price <= max_budget:
            selected.append(p)
            running += price
    return selected


def recommend_from_room(
    db: Session,
    *,
    room: Room,
    prompt: str,
    photo_ids: list[int],
    max_budget: Decimal | None,
    preferred_style: str | None,
    category_ids: list[str],
    limit: int = 6,
) -> RecommendationsResponse:
    settings = get_settings()
    candidates = filter_candidates_for_ai(
        db,
        budget=max_budget,
        category_ids=category_ids or None,
        limit=30,
    )
    catalog = _catalog_payload(candidates)
    images: list[AIImagePart] = []
    for photo in room.photos:
        if photo_ids and photo.id not in photo_ids:
            continue
        path = settings.uploads_dir / "rooms" / str(room.id) / Path(photo.relative_path).name
        if not path.is_file():
            continue
        data, mime = load_resized_image_bytes(path)
        images.append(AIImagePart(mime_type=mime, data=data))
        if len(images) >= settings.max_room_photos:
            break

    dims = {
        "width_m": float(room.width_m) if room.width_m is not None else None,
        "length_m": float(room.length_m) if room.length_m is not None else None,
        "height_m": float(room.height_m) if room.height_m is not None else None,
        "room_type": room.room_type,
        "style_preference": preferred_style or room.style_preference,
    }
    user_text = (
        f"Запрос пользователя: {prompt}\n"
        f"Комната: {room.name}\n"
        f"Контекст: {json.dumps(dims, ensure_ascii=False)}\n"
        f"Бюджет (общий максимум): {max_budget}\n"
        f"CATALOG_JSON:{json.dumps(catalog, ensure_ascii=False)}"
    )
    provider = get_ai_provider()
    result = provider.generate(
        system_prompt=SYSTEM_PROMPT,
        user_text=user_text,
        images=images,
        expect_json=True,
    )
    structured = result.structured or {}
    ranked_ids = structured.get("ranked_product_ids") or []
    reasons = structured.get("reasons") or {}

    # Validate IDs against DB / candidate set.
    valid_map = {p.id: p for p in candidates}
    ordered: list[Product] = []
    for pid in ranked_ids:
        if pid in valid_map and pid not in {p.id for p in ordered}:
            ordered.append(valid_map[pid])
    if not ordered:
        ordered = candidates[:limit]

    ordered = _apply_budget_filter(ordered, max_budget)[:limit]
    recommendations = [
        RecommendationItem(
            product_id=p.id,
            reason=str(reasons.get(p.id) or "Соответствует фильтрам каталога и бюджету."),
            product=serialize_product(p),
        )
        for p in ordered
    ]
    analysis = RoomAnalysisOut(
        summary=str(structured.get("summary") or result.text[:500]),
        observations=list(structured.get("observations") or []),
        assumptions=list(structured.get("assumptions") or []),
        uncertainties=list(structured.get("uncertainties") or []),
        missing_info=list(structured.get("missing_info") or []),
    )
    warnings: list[str] = []
    alternatives: list[RecommendationItem] = []
    if not recommendations:
        warnings.append("Подходящих товаров по жёстким ограничениям не найдено.")
        # Offer nearest catalog alternatives without inventing IDs.
        for p in candidates[: min(3, limit)]:
            alternatives.append(
                RecommendationItem(
                    product_id=p.id,
                    reason="Альтернатива из каталога вне жёсткого отбора.",
                    product=serialize_product(p),
                )
            )
    for p in ordered:
        if p.width_mm is None and p.height_mm is None and p.depth_mm is None:
            warnings.append(
                f"Габариты товара {p.id} неизвестны — совместимость с комнатой не проверена."
            )
            break

    return RecommendationsResponse(
        room_analysis=analysis,
        recommendations=recommendations,
        budget=_budget_summary(ordered, max_budget),
        explanation="Рекомендации основаны на локальном каталоге; бюджет проверен на сервере.",
        alternatives=alternatives,
        warnings=warnings,
        missing_information=list(structured.get("missing_info") or []),
    )


def chat_with_assistant(
    db: Session,
    *,
    user_id: int,
    message: str,
    session_id: int | None,
    room_id: int | None,
    photo_ids: list[int],
    budget: Decimal | None,
    style: str | None,
) -> tuple[ChatSession, str, list[str], dict[str, Any] | None]:
    settings = get_settings()
    session = None
    if session_id:
        session = (
            db.query(ChatSession)
            .filter(ChatSession.id == session_id, ChatSession.user_id == user_id)
            .first()
        )
    if not session:
        session = ChatSession(user_id=user_id, room_id=room_id, title=message[:80])
        db.add(session)
        db.commit()
        db.refresh(session)

    db.add(ChatMessage(session_id=session.id, role="user", content=message))
    db.commit()

    history = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.id.desc())
        .limit(settings.ai_history_limit)
        .all()
    )
    history = list(reversed(history))
    history_text = "\n".join(f"{m.role}: {m.content}" for m in history)

    room = db.get(Room, room_id) if room_id else None
    category_ids = _category_hints_from_text(message)
    candidates = filter_candidates_for_ai(
        db, budget=budget, category_ids=category_ids or None, limit=30
    )
    if not candidates and category_ids:
        candidates = filter_candidates_for_ai(db, budget=budget, category_ids=None, limit=30)
    # Put keyword matches first so the model sees relevant items.
    preferred = _keyword_rank(candidates, message, limit=12)
    preferred_ids = {p.id for p in preferred}
    ordered = preferred + [p for p in candidates if p.id not in preferred_ids]
    catalog = _catalog_payload(ordered[:20])

    images: list[AIImagePart] = []
    if room:
        for photo in room.photos:
            if photo_ids and photo.id not in photo_ids:
                continue
            path = settings.uploads_dir / "rooms" / str(room.id) / Path(photo.relative_path).name
            if path.is_file():
                data, mime = load_resized_image_bytes(path)
                images.append(AIImagePart(mime_type=mime, data=data))

    user_text = (
        f"Текущий запрос пользователя: {message}\n"
        f"История:\n{history_text}\n"
        f"Стиль: {style}\nБюджет: {budget}\n"
        f"CATALOG_JSON:{json.dumps(catalog, ensure_ascii=False)}"
    )
    provider = get_ai_provider()
    result = provider.generate(
        system_prompt=SYSTEM_PROMPT,
        user_text=user_text,
        images=images,
        expect_json=True,
    )
    structured = result.structured or {}
    ranked = [pid for pid in (structured.get("ranked_product_ids") or []) if get_product(db, pid)]
    if not ranked:
        ranked = [p.id for p in _keyword_rank(ordered, message, limit=3)]
        structured.setdefault("assumptions", []).append(
            "Модель не вернула id — показаны ближайшие товары из каталога по ключевым словам."
        )
    reply = str(structured.get("summary") or result.text).strip()
    if not reply or "mock AI" in reply.lower() or "макетный анализ" in reply.lower():
        names = []
        for pid in ranked[:3]:
            prod = get_product(db, pid)
            if prod:
                names.append(prod.name)
        reply = (
            "Подобрала варианты из каталога OMA: " + ", ".join(names)
            if names
            else "В локальном каталоге пока нет точного совпадения. Уточните категорию или бюджет."
        )
        structured["summary"] = reply
    db.add(
        ChatMessage(
            session_id=session.id,
            role="assistant",
            content=reply,
            meta_json=json.dumps({"product_ids": ranked}, ensure_ascii=False),
        )
    )
    db.commit()
    db.refresh(session)
    return session, reply, ranked, structured
