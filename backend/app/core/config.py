"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = BACKEND_ROOT / "data"
IS_VERCEL = bool(os.getenv("VERCEL"))
WRITABLE_ROOT = Path("/tmp/oma_dom") if IS_VERCEL else DATA_ROOT


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

    database_url: str = f"sqlite:///{(WRITABLE_ROOT / 'oma_dom.db').as_posix()}"

    cors_origins: str = "*"

    # Vercel functions can only write to /tmp. Seed assets stay read-only in the package.
    data_dir: Path = WRITABLE_ROOT
    products_json_path: Path = DATA_ROOT / "products" / "products.json"
    images_dir: Path = DATA_ROOT / "images" / "products"
    models_dir: Path = DATA_ROOT / "models" / "products"
    cache_dir: Path = WRITABLE_ROOT / "cache" / "pages"
    uploads_dir: Path = WRITABLE_ROOT / "uploads"

    max_upload_bytes: int = 8 * 1024 * 1024
    max_room_photos: int = 5
    ai_history_limit: int = 12
    rate_limit_ai_per_minute: int = 20

    # openrouter | gemini | mock (mock only for automated tests)
    ai_provider: str = "openrouter"

    # OpenRouter — preferred non-Google free vision route for MVP.
    openrouter_api_key: str | None = None
    openrouter_model: str = "nvidia/nemotron-3.5-super-vl:free"
    openrouter_fallback_models: str = (
        "qwen/qwen2.5-vl-3b-instruct:free,nvidia/nemotron-nano-12b-v2-vl:free"
    )
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "https://oma-be-85l2.onrender.com"
    openrouter_app_name: str = "OMA Dom"

    # Gemini (optional; often overloaded on free tier).
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_fallback_models: str = "gemini-2.5-flash-lite,gemini-3.8-flash"

    # Optional NVIDIA API Catalog / NIM (integrate.api.nvidia.com).
    # Prefer OpenRouter for free VL; set AI_PROVIDER=nvidia when using a NIM key.
    nvidia_api_key: str | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "nvidia/nemotron-3.5-super-vl"

    # Image generation / editing — separate from VL chat.
    # none | mock | nvidia-nim (nvidia-nim client not wired until endpoint confirmed)
    image_gen_provider: str = "none"
    image_gen_model: str | None = None
    image_gen_max_product_refs: int = 4
    image_gen_timeout_seconds: float = 120.0

    # Development loyalty rules (not official OMA program).
    loyalty_earn_rate_per_byn: float = 1.0  # 1 point per 1 BYN
    loyalty_redeem_value_per_point: float = 0.01  # 0.01 BYN per point (demo)
    loyalty_allow_negative: bool = False
    loyalty_program_label: str = "OMA Dom development loyalty (demo rules)"

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
