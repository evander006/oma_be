"""Authenticated (single-demo-user MVP) download endpoints for real PDFs."""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import Property, Room, User
from app.db.models.ecosystem import HomeEquipment, HomeHistoryEvent, WorkOrder
from app.db.session import get_db
from app.services.pdf_passport import equipment_passport_pdf, home_passport_pdf

router = APIRouter(tags=["passports"])


def _owned_property(db: Session, property_id: int, user: User) -> Property:
    prop = (
        db.query(Property)
        .filter(Property.id == property_id, Property.user_id == user.id)
        .first()
    )
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


def _download(content: bytes, filename: str) -> StreamingResponse:
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "Cache-Control": "private, no-store"},
    )


@router.get("/properties/{property_id}/passport.pdf")
def download_property_pdf(
    property_id: int, db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
) -> StreamingResponse:
    prop = _owned_property(db, property_id, user)
    rooms = db.query(Room).filter(Room.property_id == prop.id).order_by(Room.id).all()
    equipment = (
        db.query(HomeEquipment).filter(
            HomeEquipment.user_id == user.id, HomeEquipment.property_id == prop.id
        ).order_by(HomeEquipment.id).all()
    )
    history = (
        db.query(HomeHistoryEvent).filter(
            HomeHistoryEvent.user_id == user.id,
            HomeHistoryEvent.property_id == prop.id,
        ).order_by(HomeHistoryEvent.occurred_at.desc()).all()
    )
    work_orders = (
        db.query(WorkOrder).filter(
            WorkOrder.customer_id == user.id, WorkOrder.property_id == prop.id
        ).order_by(WorkOrder.id.desc()).all()
    )
    try:
        pdf = home_passport_pdf(
            prop, rooms, equipment, history, work_orders, demo=user.is_demo
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _download(pdf, f"oma_home_{prop.id}.pdf")


@router.get("/properties/{property_id}/equipment/{equipment_id}/passport.pdf")
def download_equipment_pdf(
    property_id: int, equipment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
) -> StreamingResponse:
    _owned_property(db, property_id, user)
    item = (
        db.query(HomeEquipment)
        .filter(
            HomeEquipment.id == equipment_id,
            HomeEquipment.property_id == property_id,
            HomeEquipment.user_id == user.id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Equipment not found")
    # Only history linked to the equipment's job is reliably attributable
    # to this equipment. Do not insert every unrelated property event.
    events = (
        db.query(HomeHistoryEvent)
        .filter(
            HomeHistoryEvent.user_id == user.id,
            HomeHistoryEvent.property_id == property_id,
            HomeHistoryEvent.work_order_id == item.work_order_id,
        )
        .order_by(HomeHistoryEvent.occurred_at.desc())
        .all()
        if item.work_order_id is not None else []
    )
    try:
        pdf = equipment_passport_pdf(item, events, demo=user.is_demo)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _download(pdf, f"oma_equipment_{item.id}.pdf")
