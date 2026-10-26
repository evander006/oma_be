"""FastAPI dependencies: DB session and MVP demo user (no authentication)."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_db

DEMO_EMAIL = "anna@oma.local"
DEMO_NAME = "Анна"
_LEGACY_DEMO_EMAIL = "demo@oma.local"


def get_or_create_demo_user(db: Session) -> User:
    """Single shared MVP user — Анна. No login."""
    user = (
        db.query(User)
        .filter(User.email.in_([DEMO_EMAIL, _LEGACY_DEMO_EMAIL]))
        .first()
    )
    if user:
        changed = False
        if user.email != DEMO_EMAIL:
            user.email = DEMO_EMAIL
            changed = True
        if user.display_name != DEMO_NAME:
            user.display_name = DEMO_NAME
            changed = True
        if not user.is_demo:
            user.is_demo = True
            changed = True
        if changed:
            db.commit()
            db.refresh(user)
        return user

    user = User(
        email=DEMO_EMAIL,
        display_name=DEMO_NAME,
        hashed_password=None,
        is_demo=True,
        preferred_style="современный",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_current_user(db: Session = Depends(get_db)) -> User:
    """Always returns Анна for the MVP (authentication removed)."""
    return get_or_create_demo_user(db)


def require_room_owner(db: Session, room_id: int, user: User):
    from app.db.models import Property, Room

    room = (
        db.query(Room)
        .join(Property, Room.property_id == Property.id)
        .filter(Room.id == room_id, Property.user_id == user.id)
        .first()
    )
    if not room:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    return room
