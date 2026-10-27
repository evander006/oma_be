"""Business logic for the connected digital-home ecosystem MVP."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.db.models import Cart, CartItem, Product
from app.db.models.ecosystem import (
    ContractorFavorite,
    ContractorPortfolioItem,
    ContractorProfile,
    ContractorSpecialty,
    HomeEquipment,
    HomeHistoryEvent,
    JourneyInstance,
    JourneyStepProgress,
    JourneyTemplate,
    JourneyTemplateStep,
    MaterialProposal,
    MaterialProposalItem,
    WorkOrder,
)
from app.services.asset_urls import room_photo_url
from app.services.loyalty_service import earn_points, get_or_create_account


SHAREABLE_FIELDS = {
    "address",
    "room_dimensions",
    "room_materials",
    "installed_equipment",
    "work_history",
    "photos",
}

WORK_ORDER_TRANSITIONS: dict[str, set[str]] = {
    "submitted": {"accepted", "declined"},
    "accepted": {"materials_proposed", "scheduled", "in_progress", "declined"},
    "materials_proposed": {"scheduled", "in_progress", "declined"},
    "scheduled": {"in_progress", "declined"},
    "in_progress": {"completed", "declined"},
    "completed": set(),
    "declined": set(),
}


def _json(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return fallback


def seed_ecosystem_data(db: Session) -> None:
    """Seed clearly-labelled demo contractors and project-route templates."""
    contractor_rows = [
        {
            "slug": "demo-aleksandr-electric",
            "display_name": "Александр — электромонтаж",
            "city": "Минск",
            "bio": (
                "Демонстрационный профиль для проверки сценария заявки. "
                "Не является публичной офертой или реальным рейтингом исполнителя."
            ),
            "experience_years": 7,
            "specialties": [("electrical", "Электрика"), ("lighting", "Освещение")],
            "portfolio": "Демонстрационный монтаж освещения",
        },
        {
            "slug": "demo-marina-finish",
            "display_name": "Марина — отделочные работы",
            "city": "Минск",
            "bio": (
                "Демонстрационный профиль специалиста по отделке. "
                "Данные созданы только для MVP ОМА Дом."
            ),
            "experience_years": 5,
            "specialties": [("finishing", "Отделочные работы"), ("painting", "Покраска")],
            "portfolio": "Демонстрационный ремонт комнаты",
        },
        {
            "slug": "demo-ivan-plumbing",
            "display_name": "Иван — сантехнические работы",
            "city": "Минск",
            "bio": (
                "Демонстрационный профиль для сценариев ванной и кухни. "
                "Контакты, отзывы и подтверждённые договорённости отсутствуют."
            ),
            "experience_years": 9,
            "specialties": [("plumbing", "Сантехника"), ("installation", "Установка оборудования")],
            "portfolio": "Демонстрационная установка сантехники",
        },
    ]
    for row in contractor_rows:
        contractor = (
            db.query(ContractorProfile)
            .filter(ContractorProfile.slug == row["slug"])
            .first()
        )
        if contractor:
            continue
        contractor = ContractorProfile(
            slug=row["slug"],
            display_name=row["display_name"],
            city=row["city"],
            bio=row["bio"],
            experience_years=row["experience_years"],
            rating=None,
            review_count=0,
            verified=False,
            is_demo=True,
        )
        contractor.specialties = [
            ContractorSpecialty(code=code, name=name)
            for code, name in row["specialties"]
        ]
        contractor.portfolio = [
            ContractorPortfolioItem(
                title=row["portfolio"],
                description="Демонстрационный кейс без заявления о реально выполненной работе.",
                image_url=None,
                is_demo=True,
            )
        ]
        db.add(contractor)

    journey_rows = [
        (
            "first-room",
            "Ремонт первой комнаты",
            "Понятный путь от плана до завершённой комнаты.",
            [
                ("plan", "Спланировать ремонт", ["furniture"], 25),
                ("materials", "Подобрать основные материалы", ["lighting", "furniture"], 35),
                ("finish", "Завершить проект", ["lighting-ceiling"], 50),
            ],
        ),
        (
            "first-apartment",
            "Обустройство первой квартиры",
            "Последовательное обустройство без ненужных покупок.",
            [
                ("priorities", "Определить приоритетные комнаты", ["furniture"], 25),
                ("essentials", "Выбрать необходимое", ["lighting", "furniture"], 35),
                ("install", "Организовать установку", ["plumbing-faucets"], 50),
            ],
        ),
        (
            "bathroom",
            "Ремонт ванной",
            "Маршрут с учётом сантехники и последовательности монтажа.",
            [
                ("measure", "Зафиксировать размеры и точки воды", ["plumbing-sinks"], 25),
                ("plumbing", "Подобрать сантехнику", ["plumbing-sinks", "plumbing-faucets"], 35),
                ("commission", "Завершить монтаж", ["plumbing-faucets"], 50),
            ],
        ),
        (
            "house-build",
            "Строительство дома",
            "Демонстрационный маршрут ключевых этапов строительства.",
            [
                ("plan", "Подготовить план работ", [], 25),
                ("shell", "Закрыть конструктивный этап", [], 35),
                ("utilities", "Перейти к инженерным системам", ["lighting"], 50),
            ],
        ),
        (
            "dacha-season",
            "Подготовка дачи к сезону",
            "Проверка, необходимые работы и комфорт к началу сезона.",
            [
                ("inspect", "Проверить состояние", [], 25),
                ("repair", "Выполнить необходимые работы", ["lighting"], 35),
                ("ready", "Подготовить пространство", ["furniture"], 50),
            ],
        ),
    ]
    for code, title, description, steps in journey_rows:
        template = db.query(JourneyTemplate).filter(JourneyTemplate.code == code).first()
        if template:
            continue
        template = JourneyTemplate(
            code=code,
            title=title,
            description=description,
            is_active=True,
            is_demo=True,
        )
        template.steps = [
            JourneyTemplateStep(
                code=step_code,
                title=step_title,
                description="Этап демонстрационного проектного маршрута.",
                position=position,
                recommended_categories_json=json.dumps(categories, ensure_ascii=False),
                reward_points=points,
                reward_label=f"{points} демо-баллов",
            )
            for position, (step_code, step_title, categories, points) in enumerate(steps, 1)
        ]
        db.add(template)
    db.commit()


def serialize_contractor(
    db: Session, contractor: ContractorProfile, *, user_id: int
) -> dict[str, Any]:
    is_favorite = (
        db.query(ContractorFavorite)
        .filter(
            ContractorFavorite.user_id == user_id,
            ContractorFavorite.contractor_id == contractor.id,
        )
        .first()
        is not None
    )
    return {
        "id": contractor.id,
        "display_name": contractor.display_name,
        "city": contractor.city,
        "bio": contractor.bio,
        "specialties": [s.name for s in sorted(contractor.specialties, key=lambda x: x.name)],
        "specialty_codes": [s.code for s in sorted(contractor.specialties, key=lambda x: x.code)],
        "experience_years": contractor.experience_years,
        "rating": float(contractor.rating) if contractor.rating is not None else None,
        "review_count": contractor.review_count,
        "verified": contractor.verified,
        "is_favorite": is_favorite,
        "is_demo": contractor.is_demo,
        "demo_disclaimer": (
            "Демонстрационные данные. Рейтинг и отзывы не подтверждены реальной платформой."
        ),
        "portfolio": [
            {
                "id": item.id,
                "title": item.title,
                "image_url": item.image_url,
                "description": item.description,
                "is_demo": item.is_demo,
            }
            for item in contractor.portfolio
        ],
        "reviews": [],
    }


def serialize_proposal(proposal: MaterialProposal | None) -> dict[str, Any] | None:
    if proposal is None:
        return None
    return {
        "id": proposal.id,
        "work_order_id": proposal.work_order_id,
        "status": proposal.status,
        "total_amount_byn": proposal.total_amount_byn,
        "currency": proposal.currency,
        "is_demo": proposal.is_demo,
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product_name_snapshot,
                "quantity": item.quantity,
                "unit_price_byn": item.unit_price_byn,
                "amount_byn": (
                    item.unit_price_byn * item.quantity
                    if item.unit_price_byn is not None
                    else None
                ),
            }
            for item in sorted(proposal.items, key=lambda x: x.id)
        ],
    }


def serialize_equipment(equipment: HomeEquipment) -> dict[str, Any]:
    return {
        "id": equipment.id,
        "property_id": equipment.property_id,
        "room_id": equipment.room_id,
        "product_id": equipment.product_id,
        "work_order_id": equipment.work_order_id,
        "contractor_id": equipment.contractor_id,
        "name": equipment.name,
        "quantity": equipment.quantity,
        "status": equipment.status,
        "product_snapshot": _json(equipment.product_snapshot_json, {}),
        "specifications": _json(equipment.specifications_json, {}),
        "installed_at": equipment.installed_at.isoformat() if equipment.installed_at else None,
        "notes": equipment.notes,
    }


def serialize_history_event(event: HomeHistoryEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "property_id": event.property_id,
        "room_id": event.room_id,
        "work_order_id": event.work_order_id,
        "contractor_id": event.contractor_id,
        "event_type": event.event_type,
        "title": event.title,
        "description": event.description,
        "snapshot": _json(event.snapshot_json, {}),
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
    }


def _shared_context(db: Session, order: WorkOrder, fields: list[str]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    prop = order.property
    room = order.room
    if "address" in fields:
        context["address"] = prop.address if prop else None
    if "room_dimensions" in fields:
        context["room_dimensions"] = (
            {
                "width_m": float(room.width_m) if room.width_m is not None else None,
                "length_m": float(room.length_m) if room.length_m is not None else None,
                "height_m": float(room.height_m) if room.height_m is not None else None,
            }
            if room
            else None
        )
    if "room_materials" in fields:
        context["room_materials"] = (
            {
                "wall": room.wall_material,
                "floor": room.floor_material,
                "ceiling": room.ceiling_material,
            }
            if room
            else None
        )
    if "installed_equipment" in fields:
        q = db.query(HomeEquipment).filter(HomeEquipment.user_id == order.customer_id)
        if order.property_id is not None:
            q = q.filter(HomeEquipment.property_id == order.property_id)
        if order.room_id is not None:
            q = q.filter(HomeEquipment.room_id == order.room_id)
        context["installed_equipment"] = [serialize_equipment(row) for row in q.all()]
    if "work_history" in fields:
        q = db.query(HomeHistoryEvent).filter(HomeHistoryEvent.user_id == order.customer_id)
        if order.property_id is not None:
            q = q.filter(HomeHistoryEvent.property_id == order.property_id)
        if order.room_id is not None:
            q = q.filter(HomeHistoryEvent.room_id == order.room_id)
        rows = q.order_by(HomeHistoryEvent.occurred_at.desc()).limit(20).all()
        context["work_history"] = [serialize_history_event(row) for row in rows]
    if "photos" in fields:
        context["photos"] = (
            [
                room_photo_url(room.id, Path(photo.relative_path).name)
                for photo in room.photos
            ]
            if room
            else []
        )
    return context


def serialize_work_order(
    db: Session, order: WorkOrder, *, contractor_view: bool = False
) -> dict[str, Any]:
    fields = [f for f in _json(order.shared_fields_json, []) if f in SHAREABLE_FIELDS]
    proposal = serialize_proposal(order.proposal)
    property_visible = not contractor_view or any(
        field in fields for field in {"address", "installed_equipment", "work_history"}
    )
    room_visible = not contractor_view or any(
        field in fields for field in {"room_dimensions", "room_materials", "photos"}
    )
    return {
        "id": order.id,
        "contractor_id": order.contractor_id,
        "contractor_name": order.contractor.display_name,
        "title": order.title,
        "description": order.description,
        "property_id": order.property_id if property_visible else None,
        "property_name": order.property.name if order.property and property_visible else None,
        "room_id": order.room_id if room_visible else None,
        "room_name": order.room.name if order.room and room_visible else None,
        "project_id": order.project_id if not contractor_view else None,
        "budget_byn": order.budget_byn,
        "shared_fields": fields,
        "shared_context": _shared_context(db, order, fields) if contractor_view else None,
        "status": order.status,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "completed_at": order.completed_at.isoformat() if order.completed_at else None,
        "is_demo": order.is_demo,
        "material_proposal": proposal["items"] if proposal else [],
        "proposal": proposal,
    }


def product_snapshot(product: Product) -> dict[str, Any]:
    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "brand": product.brand,
        "source_url": product.source_url,
        "price": float(product.price) if product.price is not None else None,
        "currency": product.currency,
        "width_mm": float(product.width_mm) if product.width_mm is not None else None,
        "height_mm": float(product.height_mm) if product.height_mm is not None else None,
        "depth_mm": float(product.depth_mm) if product.depth_mm is not None else None,
        "materials": product.materials,
        "colors": product.colors,
        "specifications": [
            {"name": spec.name, "value": spec.value, "unit": spec.unit}
            for spec in product.specifications
        ],
    }


def set_work_order_status(db: Session, order: WorkOrder, new_status: str) -> WorkOrder:
    if new_status == order.status:
        return order
    allowed = WORK_ORDER_TRANSITIONS.get(order.status, set())
    if new_status not in allowed:
        raise ValueError(f"Transition {order.status} -> {new_status} is not allowed")
    if new_status == "completed":
        complete_work_order(db, order)
        return order
    order.status = new_status
    db.commit()
    db.refresh(order)
    return order


def complete_work_order(db: Session, order: WorkOrder) -> None:
    """Complete once and persist an immutable product/work snapshot in the passport."""
    existing_event = (
        db.query(HomeHistoryEvent)
        .filter(
            HomeHistoryEvent.work_order_id == order.id,
            HomeHistoryEvent.event_type == "work_completed",
        )
        .first()
    )
    items_snapshot: list[dict[str, Any]] = []
    if order.proposal:
        for item in order.proposal.items:
            product = item.product
            snapshot = product_snapshot(product)
            items_snapshot.append({**snapshot, "quantity": item.quantity})
            equipment = (
                db.query(HomeEquipment)
                .filter(
                    HomeEquipment.work_order_id == order.id,
                    HomeEquipment.product_id == item.product_id,
                )
                .first()
            )
            if not equipment:
                db.add(
                    HomeEquipment(
                        user_id=order.customer_id,
                        property_id=order.property_id,
                        room_id=order.room_id,
                        product_id=item.product_id,
                        work_order_id=order.id,
                        contractor_id=order.contractor_id,
                        name=item.product_name_snapshot,
                        quantity=item.quantity,
                        status="installed",
                        product_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
                        specifications_json=json.dumps(
                            {s.name: s.value for s in product.specifications},
                            ensure_ascii=False,
                        ),
                        installed_at=datetime.now(timezone.utc),
                    )
                )
    if not existing_event:
        db.add(
            HomeHistoryEvent(
                user_id=order.customer_id,
                property_id=order.property_id,
                room_id=order.room_id,
                work_order_id=order.id,
                contractor_id=order.contractor_id,
                event_type="work_completed",
                title=f"Работа завершена: {order.title}",
                description=order.description,
                snapshot_json=json.dumps(
                    {
                        "work_order_id": order.id,
                        "contractor_id": order.contractor_id,
                        "contractor_name": order.contractor.display_name,
                        "products": items_snapshot,
                        "shared_fields": _json(order.shared_fields_json, []),
                    },
                    ensure_ascii=False,
                ),
                occurred_at=datetime.now(timezone.utc),
            )
        )
    order.status = "completed"
    order.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(order)


def accept_proposal_to_cart(
    db: Session, *, order: WorkOrder, user_id: int
) -> tuple[MaterialProposal, Cart]:
    proposal = order.proposal
    if not proposal or not proposal.items:
        raise ValueError("Material proposal is empty")
    if proposal.status == "accepted":
        cart = db.query(Cart).filter(Cart.user_id == user_id).first()
        if cart:
            return proposal, cart
    cart = db.query(Cart).filter(Cart.user_id == user_id).first()
    if not cart:
        cart = Cart(user_id=user_id, currency="BYN")
        db.add(cart)
        db.flush()
    for proposal_item in proposal.items:
        cart_item = (
            db.query(CartItem)
            .filter(
                CartItem.cart_id == cart.id,
                CartItem.product_id == proposal_item.product_id,
            )
            .first()
        )
        if cart_item:
            cart_item.quantity += proposal_item.quantity
        else:
            db.add(
                CartItem(
                    cart_id=cart.id,
                    product_id=proposal_item.product_id,
                    quantity=proposal_item.quantity,
                )
            )
    proposal.status = "accepted"
    if order.status == "materials_proposed":
        order.status = "scheduled"
    db.commit()
    db.refresh(proposal)
    db.refresh(cart)
    return proposal, cart


def serialize_journey_template(template: JourneyTemplate) -> dict[str, Any]:
    steps = sorted(template.steps, key=lambda x: x.position)
    return {
        "id": template.id,
        "code": template.code,
        "title": template.title,
        "description": template.description,
        "is_demo": template.is_demo,
        "reward_disclaimer": "Награды являются демонстрационными, не официальной скидкой OMA.",
        "steps": [
            {
                "id": step.id,
                "code": step.code,
                "title": step.title,
                "description": step.description,
                "position": step.position,
                "recommended_categories": _json(step.recommended_categories_json, []),
                "reward_points": step.reward_points,
                "reward_label": step.reward_label,
            }
            for step in steps
        ],
    }


def serialize_journey(journey: JourneyInstance) -> dict[str, Any]:
    progress_by_step = {row.step_id: row for row in journey.progress}
    steps: list[dict[str, Any]] = []
    completed = 0
    for step in sorted(journey.template.steps, key=lambda x: x.position):
        row = progress_by_step.get(step.id)
        status = row.status if row else "pending"
        if status == "completed":
            completed += 1
        steps.append(
            {
                "id": step.id,
                "code": step.code,
                "title": step.title,
                "description": step.description,
                "position": step.position,
                "recommended_categories": _json(step.recommended_categories_json, []),
                "reward_points": step.reward_points,
                "reward_label": step.reward_label,
                "status": status,
                "completed_at": (
                    row.completed_at.isoformat() if row and row.completed_at else None
                ),
                "reward_transaction_id": row.reward_transaction_id if row else None,
            }
        )
    total = len(steps)
    return {
        "id": journey.id,
        "template_id": journey.template_id,
        "project_id": journey.project_id,
        "property_id": journey.property_id,
        "title": journey.title,
        "status": journey.status,
        "progress_percent": round((completed / total) * 100) if total else 0,
        "steps": steps,
        "next_step": next((step for step in steps if step["status"] != "completed"), None),
        "started_at": journey.started_at.isoformat() if journey.started_at else None,
        "completed_at": journey.completed_at.isoformat() if journey.completed_at else None,
        "is_demo": journey.template.is_demo,
        "reward_disclaimer": "Демо-баллы не являются обещанием реальной скидки OMA.",
    }


def complete_journey_step(
    db: Session, *, journey: JourneyInstance, step_id: int
) -> dict[str, Any]:
    ordered = sorted(journey.template.steps, key=lambda x: x.position)
    target_index = next((i for i, step in enumerate(ordered) if step.id == step_id), None)
    if target_index is None:
        raise ValueError("Step does not belong to this journey")
    progress_by_step = {row.step_id: row for row in journey.progress}
    for earlier in ordered[:target_index]:
        if progress_by_step[earlier.id].status != "completed":
            raise ValueError("Complete previous journey steps first")
    progress = progress_by_step[step_id]
    if progress.status != "completed":
        step = ordered[target_index]
        progress.status = "completed"
        progress.completed_at = datetime.now(timezone.utc)
        if step.reward_points > 0:
            tx = earn_points(
                db,
                user_id=journey.user_id,
                points=step.reward_points,
                reason=f"Демо-награда маршрута «{journey.title}»: {step.title}",
                idempotency_key=f"journey-{journey.id}-step-{step.id}",
            )
            progress.reward_transaction_id = tx.id
        if target_index == len(ordered) - 1:
            journey.status = "completed"
            journey.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(journey)
    account = get_or_create_account(db, journey.user_id)
    return {
        "journey": serialize_journey(journey),
        "loyalty_balance": account.balance,
        "reward_is_demo": True,
    }
