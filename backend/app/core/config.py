"""Application configuration loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = BACKEND_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "OMA Dom API"
    app_version: str = "1.0.0"
    api_v1_prefix: str = "/api/v1"
    environment: str = "development"
    debug: bool = True
    # Kept for compatibility; authentication is disabled for the MVP.
    dev_mode: bool = True

    database_url: str = f"sqlite:///{(BACKEND_ROOT / 'data' / 'oma_dom.db').as_posix()}"

    cors_origins: str = "*"

    data_dir: Path = DATA_ROOT
    products_json_path: Path = DATA_ROOT / "products" / "products.json"
    images_dir: Path = DATA_ROOT / "images" / "products"
    models_dir: Path = DATA_ROOT / "models" / "products"
    cache_dir: Path = DATA_ROOT / "cache" / "pages"
    uploads_dir: Path = DATA_ROOT / "uploads"

    max_upload_bytes: int = 8 * 1024 * 1024
    max_room_photos: int = 5
    ai_history_limit: int = 12
    rate_limit_ai_per_minute: int = 20

    # Gemini — free-tier multimodal Flash (vision+text). Override via env.
    gemini_api_key: str | None = None
    # Prefer a stable free-tier Flash model; override via env if needed.
    gemini_model: str = "gemini-2.5-flash"
    # Comma-separated fallbacks used on 503 / high demand.
    gemini_fallback_models: str = "gemini-2.5-flash-lite,gemini-3.8-flash"
    ai_provider: str = "mock"  # mock | gemini

    oma_base_url: str = "https://www.oma.by"
    oma_request_timeout: float = 30.0
    oma_max_retries: int = 3
    oma_request_delay_seconds: float = 0.8
    oma_user_agent: str = "OMA-Dom-Parser/1.0 (+local educational MVP; respectful crawler)"
    oma_max_products: int = 20
    oma_verify_ssl: bool = True

    # Used when SSL verification fails on some local Python builds.
    oma_allow_insecure_ssl: bool = True

    default_currency: str = "BYN"
    image_retention_days: int = 30


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.images_dir.mkdir(parents=True, exist_ok=True)
    settings.models_dir.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "products").mkdir(parents=True, exist_ok=True)
    return settings
