"""Preliminary renovation estimates — no invented contractor prices."""
from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Product
from app.db.models.renovation import (
    Estimate,
    EstimateLine,
    RenovationProject,
    RenovationService,
    RenovationWorkItem,
)


def create_preliminary_estimate(
    db: Session,
    *,
    user_id: int,
    project_id: int | None = None,
    product_ids: list[str] | None = None,
    product_quantities: dict[str, Decimal] | None = None,
    work_items: list[dict] | None = None,
) -> Estimate:
    settings = get_settings()
    product_subtotal = Decimal("0")
    labor_subtotal: Decimal | None = Decimal("0")
    lines: list[EstimateLine] = []
    unknown_notes: list[str] = []
    any_unverified_labor = False

    for pid in product_ids or []:
        product = db.get(Product, pid)
        if not product:
            unknown_notes.append(f"Товар {pid} не найден в каталоге")
            continue
        qty = (product_quantities or {}).get(pid, Decimal("1"))
        price = product.price
        amount = (price * qty) if price is not None else None
        if amount is not None:
            product_subtotal += amount
        else:
            unknown_notes.append(f"Цена товара «{product.name}» неизвестна")
        lines.append(
            EstimateLine(
                line_type="product",
                product_id=product.id,
                label=product.name,
                quantity=qty,
                unit_price=price,
                amount=amount,
                verified=price is not None,
            )
        )

    for item in work_items or []:
        service_id = item.get("service_id")
        qty = Decimal(str(item.get("quantity") or 1))
        label = item.get("name") or "Работа"
        service = db.get(RenovationService, service_id) if service_id else None
        if service and service.unit_price is not None and service.price_verified:
            amount = service.unit_price * qty
            labor_subtotal = (labor_subtotal or Decimal("0")) + amount
            lines.append(
                EstimateLine(
                    line_type="labor",
                    service_id=service.id,
                    label=service.name,
                    quantity=qty,
                    unit_price=service.unit_price,
                    amount=amount,
                    verified=True,
                )
            )
        elif service and service.unit_price is not None and not service.price_verified:
            amount = service.unit_price * qty
            labor_subtotal = (labor_subtotal or Decimal("0")) + amount
            any_unverified_labor = True
            lines.append(
                EstimateLine(
                    line_type="labor",
                    service_id=service.id,
                    label=f"{service.name} (неверифицированная demo-ставка)",
                    quantity=qty,
                    unit_price=service.unit_price,
                    amount=amount,
                    verified=False,
                )
            )
            unknown_notes.append(
                f"Ставка «{service.name}» — development/demo, не официальная цена подрядчика"
            )
        else:
            any_unverified_labor = True
            lines.append(
                EstimateLine(
                    line_type="labor",
                    service_id=service.id if service else None,
                    label=label,
                    quantity=qty,
                    unit_price=None,
                    amount=None,
                    verified=False,
                )
            )
            unknown_notes.append(f"Стоимость «{label}» уточняется на консультации")

    # Pull work items from project if present
    if project_id and not work_items:
        project = db.get(RenovationProject, project_id)
        if project:
            for wi in project.work_items:
                service = db.get(RenovationService, wi.service_id) if wi.service_id else None
                qty = wi.quantity or Decimal("1")
                if service and service.unit_price is not None:
                    amount = service.unit_price * qty
                    labor_subtotal = (labor_subtotal or Decimal("0")) + amount
                    verified = bool(service.price_verified)
                    if not verified:
                        any_unverified_labor = True
                    lines.append(
                        EstimateLine(
                            line_type="labor",
                            service_id=service.id,
                            label=wi.name or service.name,
                            quantity=qty,
                            unit_price=service.unit_price,
                            amount=amount,
                            verified=verified,
                        )
                    )
                else:
                    any_unverified_labor = True
                    lines.append(
                        EstimateLine(
                            line_type="labor",
                            service_id=wi.service_id,
                            label=wi.name,
                            quantity=qty,
                            unit_price=None,
                            amount=None,
                            verified=False,
                        )
                    )
                    unknown_notes.append(f"Стоимость «{wi.name}» требует консультации")

    if labor_subtotal == Decimal("0") and any_unverified_labor:
        labor_subtotal = None

    status = "preliminary"
    if any_unverified_labor or unknown_notes:
        status = "consultation_required" if labor_subtotal is None else "incomplete"

    total = product_subtotal
    if labor_subtotal is not None:
        total += labor_subtotal

    estimate = Estimate(
        user_id=user_id,
        project_id=project_id,
        status=status,
        currency=settings.default_currency,
        product_subtotal=product_subtotal,
        labor_subtotal=labor_subtotal,
        additional_costs=None,
        unknown_costs_notes="; ".join(unknown_notes) if unknown_notes else None,
        total=total if status != "consultation_required" or product_subtotal > 0 else None,
    )
    db.add(estimate)
    db.flush()
    for line in lines:
        line.estimate_id = estimate.id
        db.add(line)
    db.commit()
    db.refresh(estimate)
    return estimate


def serialize_estimate(estimate: Estimate) -> dict:
    return {
        "id": estimate.id,
        "user_id": estimate.user_id,
        "project_id": estimate.project_id,
        "status": estimate.status,
        "currency": estimate.currency,
        "product_subtotal": estimate.product_subtotal,
        "labor_subtotal": estimate.labor_subtotal,
        "additional_costs": estimate.additional_costs,
        "unknown_costs_notes": estimate.unknown_costs_notes,
        "total": estimate.total,
        "disclaimer": estimate.disclaimer,
        "lines": [
            {
                "id": ln.id,
                "line_type": ln.line_type,
                "product_id": ln.product_id,
                "service_id": ln.service_id,
                "label": ln.label,
                "quantity": ln.quantity,
                "unit_price": ln.unit_price,
                "amount": ln.amount,
                "verified": ln.verified,
            }
            for ln in estimate.lines
        ],
        "created_at": estimate.created_at.isoformat() if estimate.created_at else None,
    }


def append_status_history(project: RenovationProject, new_status: str) -> None:
    history = []
    if project.status_history_json:
        try:
            history = json.loads(project.status_history_json)
        except json.JSONDecodeError:
            history = []
    history.append({"from": project.status, "to": new_status})
    project.status = new_status
    project.status_history_json = json.dumps(history, ensure_ascii=False)
