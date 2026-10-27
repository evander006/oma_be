"""Only actual order items, or explicitly labelled DEMO orders, enter 3D.

Cart items, wishlists, suggested products and free-form room equipment are not
proof of a purchase. For the single-user hackathon mode, demo_created orders
are allowed only for a demo user and remain labelled demonstration data.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Order, OrderItem, User


_CONFIRMED_STATUSES = frozenset({"paid", "completed", "fulfilled"})


def eligible_order_products(db: Session, user: User) -> dict[str, bool]:
    """Map product ID to is_demo. A confirmed order wins over a demo order."""
    rows = (
        db.query(OrderItem.product_id, Order.status, Order.is_demonstration)
        .join(Order, OrderItem.order_id == Order.id)
        .filter(Order.user_id == user.id)
        .all()
    )
    result: dict[str, bool] = {}
    for product_id, status, demonstration in rows:
        confirmed = not demonstration and status in _CONFIRMED_STATUSES
        demo = bool(user.is_demo and demonstration and status == "demo_created")
        if confirmed:
            result[product_id] = False
        elif demo and product_id not in result:
            result[product_id] = True
    return result
