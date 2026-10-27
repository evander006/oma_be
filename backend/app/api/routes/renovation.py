"""Renovation projects, requests, estimates, installation requests."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.db.models import User
from app.db.models.renovation import (
    Estimate,
    InstallationRequest,
    RenovationProject,
    RenovationRequest,
    RenovationService,
    RenovationWorkItem,
)
from app.db.session import get_db
from app.schemas import (
    EstimateCreate,
    InstallationRequestCreate,
    RenovationProjectCreate,
    RenovationProjectPatch,
    RenovationRequestCreate,
)
from app.services.estimate_service import (
    append_status_history,
    create_preliminary_estimate,
    serialize_estimate,
)

router = APIRouter(tags=["renovation"])

ALLOWED_STATUSES = {
    "draft",
    "submitted",
    "awaiting_consultation",
    "inspection_requested",
    "estimate_preparation",
    "estimate_confirmed",
    "scheduled",
    "in_progress",
    "completed",
    "cancelled",
}


def _serialize_project(project: RenovationProject) -> dict:
    cats = []
    if project.work_categories_json:
        try:
            cats = json.loads(project.work_categories_json)
        except json.JSONDecodeError:
            cats = []
    return {
        "id": project.id,
        "user_id": project.user_id,
        "property_id": project.property_id,
        "room_id": project.room_id,
        "name": project.name,
        "renovation_type": project.renovation_type,
        "scope": project.scope,
        "area_m2": project.area_m2,
        "room_count": project.room_count,
        "building_type": project.building_type,
        "condition": project.condition,
        "work_categories": cats,
        "budget_min": project.budget_min,
        "budget_max": project.budget_max,
        "timeline_notes": project.timeline_notes,
        "style_preferences": project.style_preferences,
        "materials_preferences": project.materials_preferences,
        "customer_notes": project.customer_notes,
        "status": project.status,
        "status_history": json.loads(project.status_history_json or "[]"),
        "contact_name": project.contact_name,
        "contact_phone": project.contact_phone,
        "address": project.address,
        "work_items": [
            {
                "id": w.id,
                "service_id": w.service_id,
                "name": w.name,
                "quantity": w.quantity,
                "unit": w.unit,
                "notes": w.notes,
            }
            for w in project.work_items
        ],
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


def _owned_project(db: Session, project_id: int, user: User) -> RenovationProject:
    project = (
        db.query(RenovationProject)
        .options(joinedload(RenovationProject.work_items))
        .filter(RenovationProject.id == project_id, RenovationProject.user_id == user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/renovation/services")
def list_renovation_services(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(RenovationService).order_by(RenovationService.name).all()
    return [
        {
            "id": s.id,
            "code": s.code,
            "name": s.name,
            "category": s.category,
            "description": s.description,
            "unit": s.unit,
            "unit_price": s.unit_price,
            "currency": s.currency,
            "price_verified": s.price_verified,
            "is_turnkey_eligible": s.is_turnkey_eligible,
            "is_standalone": s.is_standalone,
            "price_note": None
            if s.price_verified
            else "Стоимость уточняется / demo-ставка",
        }
        for s in rows
    ]


@router.post("/renovation/projects")
def create_project(
    payload: RenovationProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    project = RenovationProject(
        user_id=user.id,
        property_id=payload.property_id,
        room_id=payload.room_id,
        name=payload.name,
        renovation_type=payload.renovation_type,
        scope=payload.scope,
        area_m2=payload.area_m2,
        room_count=payload.room_count,
        building_type=payload.building_type,
        condition=payload.condition,
        work_categories_json=json.dumps(payload.work_categories, ensure_ascii=False),
        budget_min=payload.budget_min,
        budget_max=payload.budget_max,
        timeline_notes=payload.timeline_notes,
        style_preferences=payload.style_preferences,
        materials_preferences=payload.materials_preferences,
        customer_notes=payload.customer_notes,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        address=payload.address,
        status="draft",
        status_history_json=json.dumps([{"from": None, "to": "draft"}]),
    )
    db.add(project)
    db.flush()
    for item in payload.work_items:
        db.add(
            RenovationWorkItem(
                project_id=project.id,
                service_id=item.get("service_id"),
                name=item.get("name") or "Работа",
                quantity=item.get("quantity"),
                unit=item.get("unit"),
                notes=item.get("notes"),
            )
        )
    db.commit()
    db.refresh(project)
    return _serialize_project(_owned_project(db, project.id, user))


@router.get("/renovation/projects")
def list_projects(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    rows = (
        db.query(RenovationProject)
        .options(joinedload(RenovationProject.work_items))
        .filter(RenovationProject.user_id == user.id)
        .order_by(RenovationProject.id.desc())
        .all()
    )
    return [_serialize_project(p) for p in rows]


@router.get("/renovation/projects/{project_id}")
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return _serialize_project(_owned_project(db, project_id, user))


@router.patch("/renovation/projects/{project_id}")
def patch_project(
    project_id: int,
    payload: RenovationProjectPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    project = _owned_project(db, project_id, user)
    data = payload.model_dump(exclude_unset=True)
    if "status" in data:
        new_status = data.pop("status")
        if new_status not in ALLOWED_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        # Never claim scheduling confirmation via status alone
        if new_status == "scheduled":
            append_status_history(project, new_status)
            # Note in customer notes that scheduling is not confirmed by calendar
            note = (project.customer_notes or "") + (
                "\n[Система] Статус «scheduled» не означает подтверждённую дату подрядчика."
            )
            project.customer_notes = note.strip()
        else:
            append_status_history(project, new_status)
    for key, value in data.items():
        setattr(project, key, value)
    db.commit()
    return _serialize_project(_owned_project(db, project_id, user))


@router.delete("/renovation/projects/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    project = _owned_project(db, project_id, user)
    db.delete(project)
    db.commit()
    return {"deleted": True, "id": project_id}


@router.post("/renovation/requests")
def create_request(
    payload: RenovationRequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if payload.project_id:
        _owned_project(db, payload.project_id, user)
    status = "submitted" if payload.submit else "draft"
    req = RenovationRequest(
        user_id=user.id,
        project_id=payload.project_id,
        request_type=payload.request_type,
        status=status,
        notes=payload.notes,
        payload_json=json.dumps(payload.payload or {}, ensure_ascii=False),
    )
    db.add(req)
    if payload.project_id and payload.submit:
        project = _owned_project(db, payload.project_id, user)
        append_status_history(project, "submitted")
    db.commit()
    db.refresh(req)
    return {
        "id": req.id,
        "user_id": req.user_id,
        "project_id": req.project_id,
        "request_type": req.request_type,
        "status": req.status,
        "notes": req.notes,
        "payload": json.loads(req.payload_json or "{}"),
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "scheduling_note": "Заявка принята. Дата работ не подтверждена автоматически.",
    }


@router.get("/renovation/requests/{request_id}")
def get_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    req = (
        db.query(RenovationRequest)
        .filter(RenovationRequest.id == request_id, RenovationRequest.user_id == user.id)
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return {
        "id": req.id,
        "user_id": req.user_id,
        "project_id": req.project_id,
        "request_type": req.request_type,
        "status": req.status,
        "notes": req.notes,
        "payload": json.loads(req.payload_json or "{}"),
        "created_at": req.created_at.isoformat() if req.created_at else None,
    }


@router.post("/renovation/estimates")
def create_estimate(
    payload: EstimateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if payload.project_id:
        _owned_project(db, payload.project_id, user)
    estimate = create_preliminary_estimate(
        db,
        user_id=user.id,
        project_id=payload.project_id,
        product_ids=payload.product_ids,
        product_quantities=payload.product_quantities,
        work_items=payload.work_items,
    )
    return serialize_estimate(estimate)


@router.get("/renovation/estimates/{estimate_id}")
def get_estimate(
    estimate_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    estimate = (
        db.query(Estimate)
        .options(joinedload(Estimate.lines))
        .filter(Estimate.id == estimate_id, Estimate.user_id == user.id)
        .first()
    )
    if not estimate:
        raise HTTPException(status_code=404, detail="Estimate not found")
    return serialize_estimate(estimate)


@router.post("/renovation/installation-requests")
def create_installation_request(
    payload: InstallationRequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    req = InstallationRequest(
        user_id=user.id,
        product_id=payload.product_id,
        service_id=payload.service_id,
        room_id=payload.room_id,
        address=payload.address,
        preferred_dates=payload.preferred_dates,
        notes=payload.notes,
        status="submitted",
        scheduling_confirmed=False,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return {
        "id": req.id,
        "status": req.status,
        "scheduling_confirmed": False,
        "message": "Заявка на установку принята. Дата не подтверждена — требуется согласование.",
        "product_id": req.product_id,
        "service_id": req.service_id,
    }
