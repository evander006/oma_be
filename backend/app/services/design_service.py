"""Design sessions, product selection, and visualization workflow."""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import Product, Room
from app.db.models.renovation import (
    DesignSession,
    DesignVersion,
    GeneratedVisualization,
    SelectedDesignProduct,
)
from app.services.ai_capabilities import (
    build_generation_prompt,
    get_ai_capabilities,
    load_product_reference_image,
)
from app.services.ai_provider import AIImagePart
from app.services.asset_urls import serialize_product
from app.services.catalog_service import get_product
from app.services.image_service import load_resized_image_bytes
from app.services.room_analysis_service import analyze_room_photos, load_room_images

logger = get_logger(__name__)

DISCLAIMER = (
    "Концепт-визуализация. Не является точным доказательством внешнего вида, "
    "габаритов или возможности установки выбранных товаров OMA."
)


def create_design_session(
    db: Session,
    *,
    user_id: int,
    room_id: int | None,
    title: str | None,
    style: str | None,
    budget: Decimal | None,
) -> DesignSession:
    if room_id is not None:
        room = db.get(Room, room_id)
        if not room:
            raise ValueError("Room not found")
    session = DesignSession(
        user_id=user_id,
        room_id=room_id,
        title=title or "Дизайн-сессия",
        style=style,
        budget=budget,
        status="draft",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_owned_session(db: Session, session_id: int, user_id: int) -> DesignSession | None:
    return (
        db.query(DesignSession)
        .options(
            joinedload(DesignSession.versions).joinedload(DesignVersion.selected_products),
            joinedload(DesignSession.versions).joinedload(DesignVersion.visualizations),
        )
        .filter(DesignSession.id == session_id, DesignSession.user_id == user_id)
        .first()
    )


def analyze_and_attach(
    db: Session,
    *,
    session: DesignSession,
    room: Room,
    user_id: int,
    prompt: str,
    photo_ids: list[int] | None = None,
) -> DesignSession:
    structured, analysis_row = analyze_room_photos(
        db,
        room=room,
        user_id=user_id,
        prompt=prompt,
        photo_ids=photo_ids,
        style=session.style,
        budget=session.budget,
        user_room_type=room.room_type,
    )
    session.latest_analysis_id = analysis_row.id
    session.status = "analyzed"
    db.commit()
    db.refresh(session)
    return session


def create_version_with_products(
    db: Session,
    *,
    session: DesignSession,
    product_ids: list[str],
    instructions: str | None,
    photo_ids: list[int] | None = None,
    analysis_json: dict[str, Any] | None = None,
    reasons: dict[str, str] | None = None,
) -> DesignVersion:
    settings = get_settings()
    next_num = (
        max((v.version_number for v in session.versions), default=0) + 1
        if session.versions
        else 1
    )
    version = DesignVersion(
        session_id=session.id,
        version_number=next_num,
        instructions=instructions,
        analysis_json=json.dumps(analysis_json, ensure_ascii=False) if analysis_json else None,
        original_photo_ids_json=json.dumps(photo_ids or []),
        generation_status="pending",
        limitations=None,
        warnings=None,
    )
    db.add(version)
    db.flush()

    order = 0
    for pid in product_ids:
        product = get_product(db, pid)
        if not product:
            continue
        ref_path = None
        if product.images:
            primary = sorted(product.images, key=lambda i: (not i.is_primary, i.sort_order))[0]
            ref_path = primary.relative_path
        db.add(
            SelectedDesignProduct(
                version_id=version.id,
                product_id=product.id,
                reason=(reasons or {}).get(product.id),
                sort_order=order,
                reference_image_path=ref_path,
            )
        )
        order += 1

    session.status = "products_selected"
    db.commit()
    db.refresh(version)
    return version


def replace_product_in_version(
    db: Session,
    *,
    version: DesignVersion,
    old_product_id: str,
    new_product_id: str,
    reason: str | None = None,
) -> DesignVersion:
    product = get_product(db, new_product_id)
    if not product:
        raise ValueError("New product not found")
    existing = (
        db.query(SelectedDesignProduct)
        .filter(
            SelectedDesignProduct.version_id == version.id,
            SelectedDesignProduct.product_id == old_product_id,
        )
        .first()
    )
    if not existing:
        raise ValueError("Product not in this design version")
    # Avoid duplicate
    clash = (
        db.query(SelectedDesignProduct)
        .filter(
            SelectedDesignProduct.version_id == version.id,
            SelectedDesignProduct.product_id == new_product_id,
        )
        .first()
    )
    if clash and clash.id != existing.id:
        db.delete(existing)
    else:
        existing.product_id = new_product_id
        existing.reason = reason or existing.reason
        if product.images:
            primary = sorted(product.images, key=lambda i: (not i.is_primary, i.sort_order))[0]
            existing.reference_image_path = primary.relative_path
    db.commit()
    db.refresh(version)
    return version


def generate_visualization(
    db: Session,
    *,
    session: DesignSession,
    version: DesignVersion,
    room: Room | None,
    idempotency_key: str | None = None,
) -> GeneratedVisualization:
    settings = get_settings()
    if idempotency_key:
        existing = (
            db.query(DesignVersion)
            .filter(
                DesignVersion.session_id == session.id,
                DesignVersion.idempotency_key == idempotency_key,
            )
            .first()
        )
        if existing and existing.visualizations:
            return existing.visualizations[-1]
        version.idempotency_key = idempotency_key

    selected = (
        db.query(SelectedDesignProduct)
        .filter(SelectedDesignProduct.version_id == version.id)
        .order_by(SelectedDesignProduct.sort_order)
        .all()
    )
    product_meta: list[dict[str, Any]] = []
    refs: list[AIImagePart] = []
    max_refs = settings.image_gen_max_product_refs
    for sel in selected:
        product = get_product(db, sel.product_id)
        if not product:
            continue
        meta = {
            "id": product.id,
            "name": product.name,
            "width_mm": float(product.width_mm) if product.width_mm is not None else None,
            "height_mm": float(product.height_mm) if product.height_mm is not None else None,
            "depth_mm": float(product.depth_mm) if product.depth_mm is not None else None,
        }
        product_meta.append(meta)
        if len(refs) < max_refs and sel.reference_image_path:
            part = load_product_reference_image(sel.reference_image_path)
            if part:
                refs.append(part)

    prompt = build_generation_prompt(
        instructions=version.instructions or "Обнови интерьер с выбранными товарами",
        style=session.style,
        products=product_meta,
    )
    version.generation_prompt = prompt
    version.generation_status = "processing"
    db.commit()

    caps = get_ai_capabilities()
    version.provider = caps.provider_label
    version.model_id = caps.model_id

    room_image: AIImagePart | None = None
    if room:
        images = load_room_images(room, None)
        if images:
            room_image = images[0]
    if room_image is None:
        # Minimal placeholder so mock path can still run; real providers need a photo.
        room_image = AIImagePart(mime_type="image/jpeg", data=b"")

    result = caps.image_gen.generate_visualization(
        room_image=room_image,
        product_references=refs,
        prompt=prompt,
        product_meta=product_meta,
    )

    viz = GeneratedVisualization(
        version_id=version.id,
        status=result.status,
        provider=result.provider,
        model_id=result.model_id,
        error_message=result.error_message,
        disclaimer=DISCLAIMER,
    )

    if result.status == "completed" and result.image_bytes:
        dest_dir = settings.uploads_dir / "visualizations" / str(session.id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        ext = ".jpg" if (result.mime_type or "").endswith("jpeg") else ".png"
        name = f"{uuid.uuid4().hex}{ext}"
        dest = dest_dir / name
        dest.write_bytes(result.image_bytes)
        viz.relative_path = f"uploads/visualizations/{session.id}/{name}"
        version.generation_status = "completed"
    elif result.status == "unavailable":
        version.generation_status = "unavailable"
        version.limitations = "\n".join(result.limitations or [])
        version.warnings = result.error_message
    else:
        version.generation_status = result.status or "failed"
        version.warnings = result.error_message
        viz.error_message = result.error_message

    db.add(viz)
    session.status = (
        "visualization_ready"
        if version.generation_status == "completed"
        else "visualization_pending"
    )
    db.commit()
    db.refresh(viz)
    return viz


def serialize_session(session: DesignSession) -> dict[str, Any]:
    settings = get_settings()
    versions_out = []
    for v in sorted(session.versions, key=lambda x: x.version_number):
        products_out = []
        for sp in sorted(v.selected_products, key=lambda x: x.sort_order):
            prod = sp.product_id
            # product may need loading — serialize id/reason; caller can enrich
            products_out.append(
                {
                    "product_id": sp.product_id,
                    "reason": sp.reason,
                    "sort_order": sp.sort_order,
                    "reference_image_path": sp.reference_image_path,
                }
            )
        viz_out = []
        for viz in v.visualizations:
            url = None
            if viz.relative_path:
                filename = Path(viz.relative_path).name
                url = f"{settings.api_v1_prefix}/assets/visualizations/{session.id}/{filename}"
            viz_out.append(
                {
                    "id": viz.id,
                    "status": viz.status,
                    "url": url,
                    "provider": viz.provider,
                    "model_id": viz.model_id,
                    "error_message": viz.error_message,
                    "disclaimer": viz.disclaimer,
                    "created_at": viz.created_at.isoformat() if viz.created_at else None,
                }
            )
        versions_out.append(
            {
                "id": v.id,
                "version_number": v.version_number,
                "instructions": v.instructions,
                "generation_status": v.generation_status,
                "generation_prompt": v.generation_prompt,
                "provider": v.provider,
                "model_id": v.model_id,
                "limitations": v.limitations,
                "warnings": v.warnings,
                "selected_products": products_out,
                "visualizations": viz_out,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
        )
    return {
        "id": session.id,
        "user_id": session.user_id,
        "room_id": session.room_id,
        "title": session.title,
        "style": session.style,
        "budget": float(session.budget) if session.budget is not None else None,
        "status": session.status,
        "latest_analysis_id": session.latest_analysis_id,
        "versions": versions_out,
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


def enrich_version_products(db: Session, version_payload: dict[str, Any]) -> dict[str, Any]:
    for item in version_payload.get("selected_products") or []:
        p = get_product(db, item["product_id"])
        if p:
            item["product"] = serialize_product(p).model_dump(mode="json")
    return version_payload
