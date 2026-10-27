"""Configurable development loyalty engine (not official OMA rules)."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.renovation import LoyaltyAccount, LoyaltyTransaction


class LoyaltyError(ValueError):
    pass


def get_or_create_account(db: Session, user_id: int) -> LoyaltyAccount:
    settings = get_settings()
    account = db.query(LoyaltyAccount).filter(LoyaltyAccount.user_id == user_id).first()
    if account:
        return account
    account = LoyaltyAccount(
        user_id=user_id,
        balance=0,
        tier="standard",
        program_label=settings.loyalty_program_label,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _apply_tx(
    db: Session,
    *,
    account: LoyaltyAccount,
    kind: str,
    points: int,
    reason: str | None,
    order_id: int | None,
    idempotency_key: str | None,
) -> LoyaltyTransaction:
    settings = get_settings()
    if idempotency_key:
        existing = (
            db.query(LoyaltyTransaction)
            .filter(LoyaltyTransaction.idempotency_key == idempotency_key)
            .first()
        )
        if existing:
            return existing

    if kind == "earn":
        if points <= 0:
            raise LoyaltyError("Earn points must be positive")
        new_balance = account.balance + points
        stored_points = points
    elif kind == "redeem":
        if points <= 0:
            raise LoyaltyError("Redeem points must be positive")
        new_balance = account.balance - points
        if new_balance < 0 and not settings.loyalty_allow_negative:
            raise LoyaltyError("Insufficient loyalty balance")
        stored_points = -points
    elif kind == "reversal":
        # `points` is the delta applied to balance (opposite of original.points).
        new_balance = account.balance + points
        if new_balance < 0 and not settings.loyalty_allow_negative:
            raise LoyaltyError("Reversal would make balance negative")
        stored_points = points
    else:
        raise LoyaltyError(f"Unknown transaction kind: {kind}")

    account.balance = new_balance
    tx = LoyaltyTransaction(
        account_id=account.id,
        kind=kind,
        points=stored_points,
        balance_after=new_balance,
        reason=reason,
        order_id=order_id,
        idempotency_key=idempotency_key,
    )
    db.add(tx)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if idempotency_key:
            existing = (
                db.query(LoyaltyTransaction)
                .filter(LoyaltyTransaction.idempotency_key == idempotency_key)
                .first()
            )
            if existing:
                return existing
        raise
    db.refresh(tx)
    db.refresh(account)
    return tx


def earn_for_order(
    db: Session,
    *,
    user_id: int,
    order_id: int,
    order_total: Decimal,
    idempotency_key: str,
) -> LoyaltyTransaction:
    settings = get_settings()
    account = get_or_create_account(db, user_id)
    points = int(order_total * Decimal(str(settings.loyalty_earn_rate_per_byn)))
    existing = (
        db.query(LoyaltyTransaction)
        .filter(LoyaltyTransaction.idempotency_key == idempotency_key)
        .first()
    )
    if existing:
        return existing
    if points <= 0:
        # Idempotent no-op marker with 0 stored via reversal-style skip: earn min 1 only
        # when total > 0; otherwise return synthetic zero without writing.
        raise LoyaltyError("Order total too small to earn points")
    return _apply_tx(
        db,
        account=account,
        kind="earn",
        points=points,
        reason=f"Начисление за заказ #{order_id} (demo rules)",
        order_id=order_id,
        idempotency_key=idempotency_key,
    )


def earn_points(
    db: Session,
    *,
    user_id: int,
    points: int,
    reason: str,
    idempotency_key: str,
    order_id: int | None = None,
) -> LoyaltyTransaction:
    account = get_or_create_account(db, user_id)
    return _apply_tx(
        db,
        account=account,
        kind="earn",
        points=points,
        reason=reason,
        order_id=order_id,
        idempotency_key=idempotency_key,
    )


def redeem_points(
    db: Session,
    *,
    user_id: int,
    points: int,
    reason: str,
    idempotency_key: str,
) -> LoyaltyTransaction:
    account = get_or_create_account(db, user_id)
    return _apply_tx(
        db,
        account=account,
        kind="redeem",
        points=points,
        reason=reason,
        order_id=None,
        idempotency_key=idempotency_key,
    )


def reverse_transaction(
    db: Session,
    *,
    user_id: int,
    original_tx_id: int,
    idempotency_key: str,
) -> LoyaltyTransaction:
    account = get_or_create_account(db, user_id)
    original = (
        db.query(LoyaltyTransaction)
        .filter(
            LoyaltyTransaction.id == original_tx_id,
            LoyaltyTransaction.account_id == account.id,
        )
        .first()
    )
    if not original:
        raise LoyaltyError("Original transaction not found")
    # Reverse by applying opposite delta
    return _apply_tx(
        db,
        account=account,
        kind="reversal",
        points=-original.points,
        reason=f"Reversal of tx #{original.id}",
        order_id=original.order_id,
        idempotency_key=idempotency_key,
    )


def list_rewards_catalog() -> list[dict]:
    """Demo rewards — explicitly labeled development."""
    settings = get_settings()
    return [
        {
            "id": "demo-discount-10",
            "title": "Скидка 10 BYN (demo)",
            "points_cost": 1000,
            "description": "Демо-вознаграждение. Не официальная программа лояльности OMA.",
            "program_label": settings.loyalty_program_label,
        },
        {
            "id": "demo-consult",
            "title": "Консультация дизайнера (demo)",
            "points_cost": 2500,
            "description": "Демо-вознаграждение. Требует ручного подтверждения.",
            "program_label": settings.loyalty_program_label,
        },
    ]


def serialize_account(account: LoyaltyAccount) -> dict:
    settings = get_settings()
    return {
        "id": account.id,
        "user_id": account.user_id,
        "balance": account.balance,
        "tier": account.tier,
        "program_label": account.program_label,
        "earn_rate_per_byn": settings.loyalty_earn_rate_per_byn,
        "redeem_value_per_point": settings.loyalty_redeem_value_per_point,
        "is_development_config": True,
    }
