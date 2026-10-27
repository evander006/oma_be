"""Loyalty account APIs — development rules only."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import User
from app.db.models.renovation import LoyaltyTransaction
from app.db.session import get_db
from app.schemas import LoyaltyEarnRequest, LoyaltyRedeemRequest
from app.services.loyalty_service import (
    LoyaltyError,
    earn_points,
    get_or_create_account,
    list_rewards_catalog,
    redeem_points,
    serialize_account,
)

router = APIRouter(prefix="/loyalty", tags=["loyalty"])


@router.get("/account")
def loyalty_account(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    account = get_or_create_account(db, user.id)
    return serialize_account(account)


@router.get("/transactions")
def loyalty_transactions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    account = get_or_create_account(db, user.id)
    rows = (
        db.query(LoyaltyTransaction)
        .filter(LoyaltyTransaction.account_id == account.id)
        .order_by(LoyaltyTransaction.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": t.id,
            "kind": t.kind,
            "points": t.points,
            "balance_after": t.balance_after,
            "reason": t.reason,
            "order_id": t.order_id,
            "idempotency_key": t.idempotency_key,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in rows
    ]


@router.get("/rewards")
def loyalty_rewards() -> list[dict]:
    return list_rewards_catalog()


@router.post("/earn")
def loyalty_earn(
    payload: LoyaltyEarnRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Dev/admin-style earn endpoint for tests and demo. Client cannot set balance directly."""
    try:
        tx = earn_points(
            db,
            user_id=user.id,
            points=payload.points,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
            order_id=payload.order_id,
        )
    except LoyaltyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    account = get_or_create_account(db, user.id)
    return {
        "transaction_id": tx.id,
        "points": tx.points,
        "balance": account.balance,
        "kind": tx.kind,
    }


@router.post("/redeem")
def loyalty_redeem(
    payload: LoyaltyRedeemRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        tx = redeem_points(
            db,
            user_id=user.id,
            points=payload.points,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
        )
    except LoyaltyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    account = get_or_create_account(db, user.id)
    return {
        "transaction_id": tx.id,
        "points": tx.points,
        "balance": account.balance,
        "kind": tx.kind,
    }
