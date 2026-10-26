from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    provider = (settings.ai_provider or "openrouter").lower()
    if provider == "openrouter":
        model = settings.openrouter_model
    elif provider == "gemini":
        model = settings.gemini_model
    elif provider == "mock":
        model = "mock"
    else:
        model = provider
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        environment=settings.environment,
        ai_provider=settings.ai_provider,
        ai_model=model,
        demo_user="Анна",
    )
