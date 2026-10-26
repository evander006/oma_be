"""MVP profile — no authentication."""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.db.models import User
from app.schemas import UserOut

router = APIRouter(tags=["profile"])


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    """Current MVP user (always Анна)."""
    return user
