"""Connected home passport, contractors, work orders and project journeys."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, require_room_owner
from app.db.models import CartItem, Product, Property, Room, User
from app.db.models.ecosystem import (
    ContractorFavorite,
    ContractorProfile,
    HomeEquipment,
    HomeHistoryEvent,
    JourneyInstance,
    JourneyStepProgress,
    JourneyTemplate,
    MaterialProposal,
    MaterialProposalItem,
    WorkOrder,
)
from app.db.models.renovation import RenovationProject
from app.db.session import get_db
from app.schemas import PropertyOut, RoomOut
from app.schemas.ecosystem import (
    HomeEquipmentCreate,
    JourneyCreate,
    MaterialProposalCreate,
    PropertyPatch,
    RoomPatch,
    WorkOrderCreate,
    WorkOrderStatusPatch,
)
from app.services.ecosystem_service import (
    SHAREABLE_FIELDS,
    accept_proposal_to_cart,
    complete_journey_step,
    product_snapshot,
    serialize_contractor,
    serialize_equipment,
    serialize_history_event,
    serialize_journey,
    serialize_journey_template,
    serialize_proposal,
    serialize_work_order,
    set_work_order_status,
)

router = APIRouter(tags=["ecosystem"])


def _owned_property(db: Session, property_id: int, user: User) -> Property:
    prop = (
        db.query(Property)
        .filter(Property.id == property_id, Property.user_id == user.id)
        .first()
    )
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


def _owned_project(db: Session, project_id: int, user: User) -> RenovationProject:
    project = (
        db.query(RenovationProject)
        .filter(RenovationProject.id == project_id, RenovationProject.user_id == user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _work_order_query(db: Session):
    return db.query(WorkOrder).options(
        joinedload(WorkOrder.contractor).joinedload(ContractorProfile.specialties),
        joinedload(WorkOrder.property),
        joinedload(WorkOrder.room).joinedload(Room.photos),
        joinedload(WorkOrder.project),
        joinedload(WorkOrder.proposal)
        .joinedload(MaterialProposal.items)
        .joinedload(MaterialProposalItem.product),
    )


def _owned_work_order(db: Session, work_order_id: int, user: User) -> WorkOrder:
    order = (
        _work_order_query(db)
        .filter(WorkOrder.id == work_order_id, WorkOrder.customer_id == user.id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Work order not found")
    return order


def _demo_contractor_access(
    order: WorkOrder, x_contractor_id: int | None
) -> None:
    """Scope the demo dashboard when a contractor header is supplied.

    Real authentication is outside the current repository's MVP auth mode.  In
    demo mode an omitted header means "open the assigned contractor's demo
    dashboard"; a supplied mismatching id is always rejected.
    """
    if x_contractor_id is not None and x_contractor_id != order.contractor_id:
        raise HTTPException(status_code=403, detail="Work order belongs to another contractor")
    if not order.contractor.is_demo:
        raise HTTPException(status_code=401, detail="Contractor authentication required")


# ---------------------------------------------------------------------------
# Home passport
# ---------------------------------------------------------------------------


@router.patch("/properties/{property_id}", response_model=PropertyOut)
def patch_property(
    property_id: int,
    payload: PropertyPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Property:
    prop = _owned_property(db, property_id, user)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(prop, key, value)
    db.commit()
    db.refresh(prop)
    return prop


@router.patch("/rooms/{room_id}", response_model=RoomOut)
def patch_room(
    room_id: int,
    payload: RoomPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Room:
    room = require_room_owner(db, room_id, user)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(room, key, value)
    db.commit()
    db.refresh(room)
    return room


@router.get("/properties/{property_id}/equipment")
def property_equipment(
    property_id: int,
    room_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    _owned_property(db, property_id, user)
    q = db.query(HomeEquipment).filter(
        HomeEquipment.user_id == user.id,
        HomeEquipment.property_id == property_id,
    )
    if room_id is not None:
        room = require_room_owner(db, room_id, user)
        if room.property_id != property_id:
            raise HTTPException(status_code=400, detail="Room does not belong to property")
        q = q.filter(HomeEquipment.room_id == room_id)
    rows = q.order_by(HomeEquipment.installed_at.desc()).all()
    return [serialize_equipment(row) for row in rows]


@router.post("/properties/{property_id}/equipment", status_code=201)
def add_property_equipment(
    property_id: int,
    payload: HomeEquipmentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _owned_property(db, property_id, user)
    if payload.room_id is not None:
        room = require_room_owner(db, payload.room_id, user)
        if room.property_id != property_id:
            raise HTTPException(status_code=400, detail="Room does not belong to property")
    product = db.get(Product, payload.product_id) if payload.product_id else None
    if payload.product_id and not product:
        raise HTTPException(status_code=404, detail="Product not found")
    contractor = (
        db.get(ContractorProfile, payload.contractor_id)
        if payload.contractor_id is not None
        else None
    )
    if payload.contractor_id is not None and not contractor:
        raise HTTPException(status_code=404, detail="Contractor not found")
    snapshot = product_snapshot(product) if product else {"name": payload.name, "source": "manual"}
    equipment = HomeEquipment(
        user_id=user.id,
        property_id=property_id,
        room_id=payload.room_id,
        product_id=payload.product_id,
        contractor_id=payload.contractor_id,
        name=payload.name,
        quantity=payload.quantity,
        status=payload.status,
        product_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        specifications_json=json.dumps(payload.specifications, ensure_ascii=False),
        installed_at=payload.installed_at or datetime.now(timezone.utc),
        notes=payload.notes,
    )
    db.add(equipment)
    db.flush()
    db.add(
        HomeHistoryEvent(
            user_id=user.id,
            property_id=property_id,
            room_id=payload.room_id,
            contractor_id=payload.contractor_id,
            event_type="equipment_added",
            title=f"Добавлено оборудование: {payload.name}",
            description=payload.notes,
            snapshot_json=json.dumps(
                {"equipment_id": equipment.id, "product": snapshot}, ensure_ascii=False
            ),
            occurred_at=equipment.installed_at,
        )
    )
    db.commit()
    db.refresh(equipment)
    return serialize_equipment(equipment)


@router.get("/properties/{property_id}/history")
def property_history(
    property_id: int,
    room_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    _owned_property(db, property_id, user)
    q = db.query(HomeHistoryEvent).filter(
        HomeHistoryEvent.user_id == user.id,
        HomeHistoryEvent.property_id == property_id,
    )
    if room_id is not None:
        room = require_room_owner(db, room_id, user)
        if room.property_id != property_id:
            raise HTTPException(status_code=400, detail="Room does not belong to property")
        q = q.filter(HomeHistoryEvent.room_id == room_id)
    rows = q.order_by(HomeHistoryEvent.occurred_at.desc()).all()
    return [serialize_history_event(row) for row in rows]


# ---------------------------------------------------------------------------
# Demo contractor catalog
# ---------------------------------------------------------------------------


@router.get("/contractors")
def contractors(
    specialty: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    q = db.query(ContractorProfile).options(
        joinedload(ContractorProfile.specialties),
        joinedload(ContractorProfile.portfolio),
    )
    rows = q.order_by(ContractorProfile.display_name).all()
    # SQLite's LIKE/LOWER do not case-fold Cyrillic reliably. These demo
    # profiles form a small catalog; Unicode-aware filtering on loaded
    # specialties behaves consistently across SQLite and PostgreSQL.
    needle = (specialty or "").strip().casefold()
    if needle:
        rows = [
            contractor
            for contractor in rows
            if any(
                needle in specialty.code.casefold()
                or needle in specialty.name.casefold()
                for specialty in contractor.specialties
            )
        ]
    return [serialize_contractor(db, row, user_id=user.id) for row in rows]


@router.get("/contractors/{contractor_id}")
def contractor_detail(
    contractor_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    contractor = (
        db.query(ContractorProfile)
        .options(
            joinedload(ContractorProfile.specialties),
            joinedload(ContractorProfile.portfolio),
        )
        .filter(ContractorProfile.id == contractor_id)
        .first()
    )
    if not contractor:
        raise HTTPException(status_code=404, detail="Contractor not found")
    return serialize_contractor(db, contractor, user_id=user.id)


@router.post("/contractors/{contractor_id}/favorite")
def favorite_contractor(
    contractor_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if not db.get(ContractorProfile, contractor_id):
        raise HTTPException(status_code=404, detail="Contractor not found")
    favorite = (
        db.query(ContractorFavorite)
        .filter(
            ContractorFavorite.user_id == user.id,
            ContractorFavorite.contractor_id == contractor_id,
        )
        .first()
    )
    if not favorite:
        favorite = ContractorFavorite(user_id=user.id, contractor_id=contractor_id)
        db.add(favorite)
        db.commit()
        db.refresh(favorite)
    return {"contractor_id": contractor_id, "is_favorite": True}


@router.delete("/contractors/{contractor_id}/favorite")
def unfavorite_contractor(
    contractor_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    favorite = (
        db.query(ContractorFavorite)
        .filter(
            ContractorFavorite.user_id == user.id,
            ContractorFavorite.contractor_id == contractor_id,
        )
        .first()
    )
    if favorite:
        db.delete(favorite)
        db.commit()
    return {"contractor_id": contractor_id, "is_favorite": False}


# ---------------------------------------------------------------------------
# Structured work orders and product proposals
# ---------------------------------------------------------------------------


@router.post("/work-orders", status_code=201)
def create_work_order(
    payload: WorkOrderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    contractor = db.get(ContractorProfile, payload.contractor_id)
    if not contractor:
        raise HTTPException(status_code=404, detail="Contractor not found")
    unknown = sorted(set(payload.shared_fields) - SHAREABLE_FIELDS)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail={"message": "Unsupported shared fields", "fields": unknown},
        )
    if not payload.consent_granted:
        raise HTTPException(status_code=400, detail="Explicit data-sharing consent is required")

    prop = _owned_property(db, payload.property_id, user) if payload.property_id else None
    room = require_room_owner(db, payload.room_id, user) if payload.room_id else None
    if room and prop and room.property_id != prop.id:
        raise HTTPException(status_code=400, detail="Room does not belong to property")
    if room and not prop:
        prop = _owned_property(db, room.property_id, user)
    project = _owned_project(db, payload.project_id, user) if payload.project_id else None
    if project and prop and project.property_id and project.property_id != prop.id:
        raise HTTPException(status_code=400, detail="Project belongs to another property")
    if project and room and project.room_id and project.room_id != room.id:
        raise HTTPException(status_code=400, detail="Project belongs to another room")

    needs_room = {"room_dimensions", "room_materials", "photos"}
    if set(payload.shared_fields) & needs_room and not room:
        raise HTTPException(status_code=400, detail="Selected shared fields require a room")
    needs_property = {"address", "installed_equipment", "work_history"}
    if set(payload.shared_fields) & needs_property and not prop:
        raise HTTPException(status_code=400, detail="Selected shared fields require a property")

    order = WorkOrder(
        customer_id=user.id,
        contractor_id=contractor.id,
        property_id=prop.id if prop else None,
        room_id=room.id if room else None,
        project_id=project.id if project else None,
        title=payload.title,
        description=payload.description,
        budget_byn=payload.budget_byn,
        shared_fields_json=json.dumps(payload.shared_fields, ensure_ascii=False),
        consent_granted=True,
        status="submitted",
        is_demo=True,
    )
    db.add(order)
    db.commit()
    order = _work_order_query(db).filter(WorkOrder.id == order.id).first()
    return serialize_work_order(db, order)


@router.get("/work-orders/mine")
def my_work_orders(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    rows = (
        _work_order_query(db)
        .filter(WorkOrder.customer_id == user.id)
        .order_by(WorkOrder.id.desc())
        .all()
    )
    return [serialize_work_order(db, row) for row in rows]


@router.get("/contractor/work-orders")
def contractor_work_orders(
    contractor_id: int | None = Query(default=None),
    x_contractor_id: int | None = Header(default=None, alias="X-Contractor-Id"),
    db: Session = Depends(get_db),
) -> list[dict]:
    selected_id = x_contractor_id if x_contractor_id is not None else contractor_id
    q = _work_order_query(db)
    if selected_id is not None:
        contractor = db.get(ContractorProfile, selected_id)
        if not contractor:
            raise HTTPException(status_code=404, detail="Contractor not found")
        if not contractor.is_demo:
            raise HTTPException(status_code=401, detail="Contractor authentication required")
        q = q.filter(WorkOrder.contractor_id == selected_id)
    else:
        # Authentication is disabled in the original MVP.  Without a selected
        # demo profile, show only demo work orders and still redact context.
        q = q.join(ContractorProfile).filter(ContractorProfile.is_demo.is_(True))
    rows = q.order_by(WorkOrder.id.desc()).all()
    return [serialize_work_order(db, row, contractor_view=True) for row in rows]


@router.patch("/work-orders/{work_order_id}/status")
def patch_work_order_status(
    work_order_id: int,
    payload: WorkOrderStatusPatch,
    x_contractor_id: int | None = Header(default=None, alias="X-Contractor-Id"),
    db: Session = Depends(get_db),
) -> dict:
    order = _work_order_query(db).filter(WorkOrder.id == work_order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Work order not found")
    _demo_contractor_access(order, x_contractor_id)
    try:
        set_work_order_status(db, order, payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    order = _work_order_query(db).filter(WorkOrder.id == work_order_id).first()
    return serialize_work_order(db, order, contractor_view=True)


@router.get("/work-orders/{work_order_id}/proposal")
def get_work_order_proposal(
    work_order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    order = _owned_work_order(db, work_order_id, user)
    proposal = serialize_proposal(order.proposal)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Material proposal not found")
    return proposal


@router.post("/work-orders/{work_order_id}/proposal")
def create_material_proposal(
    work_order_id: int,
    payload: MaterialProposalCreate,
    x_contractor_id: int | None = Header(default=None, alias="X-Contractor-Id"),
    db: Session = Depends(get_db),
) -> dict:
    order = _work_order_query(db).filter(WorkOrder.id == work_order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Work order not found")
    _demo_contractor_access(order, x_contractor_id)
    if order.status not in {"accepted", "materials_proposed"}:
        raise HTTPException(status_code=409, detail="Accept the work order before proposing materials")

    product_ids = [item.product_id for item in payload.items]
    if len(set(product_ids)) != len(product_ids):
        raise HTTPException(status_code=400, detail="Each product may appear only once")
    products = {
        product.id: product
        for product in db.query(Product).filter(Product.id.in_(product_ids)).all()
    }
    missing = [product_id for product_id in product_ids if product_id not in products]
    if missing:
        raise HTTPException(status_code=404, detail={"products_not_found": missing})

    proposal = order.proposal
    if proposal and proposal.status == "accepted":
        raise HTTPException(status_code=409, detail="Accepted proposal cannot be changed")
    if not proposal:
        proposal = MaterialProposal(
            work_order_id=order.id,
            contractor_id=order.contractor_id,
            status="sent",
            is_demo=True,
        )
        db.add(proposal)
        db.flush()
    else:
        proposal.items.clear()
        db.flush()

    total = Decimal("0")
    for requested in payload.items:
        product = products[requested.product_id]
        if product.price is not None:
            total += product.price * requested.quantity
        proposal.items.append(
            MaterialProposalItem(
                product_id=product.id,
                product_name_snapshot=product.name,
                quantity=requested.quantity,
                unit_price_byn=product.price,
            )
        )
    proposal.total_amount_byn = total
    proposal.status = "sent"
    order.status = "materials_proposed"
    db.commit()
    order = _work_order_query(db).filter(WorkOrder.id == order.id).first()
    return serialize_proposal(order.proposal)


@router.post("/work-orders/{work_order_id}/proposal/accept")
def accept_material_proposal(
    work_order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    order = _owned_work_order(db, work_order_id, user)
    try:
        proposal, cart = accept_proposal_to_cart(db, order=order, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    cart_items = (
        db.query(CartItem)
        .filter(CartItem.cart_id == cart.id)
        .order_by(CartItem.id)
        .all()
    )
    return {
        "proposal": serialize_proposal(proposal),
        "cart": {
            "id": cart.id,
            "items": [
                {"product_id": item.product_id, "quantity": item.quantity}
                for item in cart_items
            ],
        },
        "status": "scheduled",
    }


# ---------------------------------------------------------------------------
# Project bonus journeys (demo rewards through existing loyalty ledger)
# ---------------------------------------------------------------------------


@router.get("/journeys/templates")
def journey_templates(db: Session = Depends(get_db)) -> list[dict]:
    rows = (
        db.query(JourneyTemplate)
        .options(joinedload(JourneyTemplate.steps))
        .filter(JourneyTemplate.is_active.is_(True))
        .order_by(JourneyTemplate.id)
        .all()
    )
    return [serialize_journey_template(row) for row in rows]


@router.post("/journeys", status_code=201)
def create_journey(
    payload: JourneyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    template = (
        db.query(JourneyTemplate)
        .options(joinedload(JourneyTemplate.steps))
        .filter(
            JourneyTemplate.id == payload.template_id,
            JourneyTemplate.is_active.is_(True),
        )
        .first()
    )
    if not template:
        raise HTTPException(status_code=404, detail="Journey template not found")
    prop = _owned_property(db, payload.property_id, user) if payload.property_id else None
    project = _owned_project(db, payload.project_id, user) if payload.project_id else None
    if project and prop and project.property_id and project.property_id != prop.id:
        raise HTTPException(status_code=400, detail="Project belongs to another property")
    if project and not prop and project.property_id:
        prop = _owned_property(db, project.property_id, user)
    journey = JourneyInstance(
        user_id=user.id,
        template_id=template.id,
        project_id=project.id if project else None,
        property_id=prop.id if prop else None,
        title=payload.title or template.title,
        status="active",
    )
    db.add(journey)
    db.flush()
    for step in template.steps:
        db.add(
            JourneyStepProgress(
                journey_id=journey.id,
                step_id=step.id,
                status="pending",
            )
        )
    db.commit()
    journey = (
        db.query(JourneyInstance)
        .options(
            joinedload(JourneyInstance.template).joinedload(JourneyTemplate.steps),
            joinedload(JourneyInstance.progress),
        )
        .filter(JourneyInstance.id == journey.id)
        .first()
    )
    return serialize_journey(journey)


@router.get("/journeys")
def list_journeys(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    rows = (
        db.query(JourneyInstance)
        .options(
            joinedload(JourneyInstance.template).joinedload(JourneyTemplate.steps),
            joinedload(JourneyInstance.progress),
        )
        .filter(JourneyInstance.user_id == user.id)
        .order_by(JourneyInstance.id.desc())
        .all()
    )
    return [serialize_journey(row) for row in rows]


@router.get("/journeys/{journey_id}")
def get_journey(
    journey_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    journey = (
        db.query(JourneyInstance)
        .options(
            joinedload(JourneyInstance.template).joinedload(JourneyTemplate.steps),
            joinedload(JourneyInstance.progress),
        )
        .filter(JourneyInstance.id == journey_id, JourneyInstance.user_id == user.id)
        .first()
    )
    if not journey:
        raise HTTPException(status_code=404, detail="Journey not found")
    return serialize_journey(journey)


@router.post("/journeys/{journey_id}/steps/{step_id}/complete")
def complete_step(
    journey_id: int,
    step_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    journey = (
        db.query(JourneyInstance)
        .options(
            joinedload(JourneyInstance.template).joinedload(JourneyTemplate.steps),
            joinedload(JourneyInstance.progress),
        )
        .filter(JourneyInstance.id == journey_id, JourneyInstance.user_id == user.id)
        .first()
    )
    if not journey:
        raise HTTPException(status_code=404, detail="Journey not found")
    try:
        return complete_journey_step(db, journey=journey, step_id=step_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
