"""FastAPI application entrypoint for OMA. Дом backend."""
from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api.deps import get_or_create_demo_user
from app.api.routes import ai, assets, commerce, health, products, profile, rooms
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.base import Base
from app.db.models import InstallationService, Product
from app.db.session import SessionLocal, engine
from app.services.catalog_service import ensure_seed_categories, upsert_products_from_json

logger = get_logger(__name__)


def seed_installation_services() -> None:
    db = SessionLocal()
    try:
        if db.query(InstallationService).count() == 0:
            db.add_all(
                [
                    InstallationService(
                        code="basic_install",
                        name="Базовый монтаж",
                        description="Демонстрационная услуга установки одного изделия",
                        price=Decimal("49.00"),
                        estimated_hours=Decimal("2"),
                    ),
                    InstallationService(
                        code="complex_install",
                        name="Комплексный монтаж",
                        description="Демонстрационный пакет для нескольких изделий",
                        price=Decimal("129.00"),
                        estimated_hours=Decimal("5"),
                    ),
                ]
            )
            db.commit()
        ensure_seed_categories(db)
        get_or_create_demo_user(db)
    finally:
        db.close()


def seed_catalog_from_json_if_empty() -> None:
    """On Render/ephemeral disk, rebuild catalog from baked-in products.json."""
    settings = get_settings()
    db = SessionLocal()
    try:
        if db.query(Product).count() > 0:
            return
        if not settings.products_json_path.is_file():
            logger.warning("No products.json found; catalog stays empty")
            return
        stats = upsert_products_from_json(db, settings.products_json_path)
        logger.info("Seeded catalog from JSON: %s", stats)
        for product in db.query(Product).all():
            glb = settings.models_dir / f"{product.id}.glb"
            if glb.is_file():
                product.has_3d_model = True
                product.model_path = f"models/products/{product.id}.glb"
                product.model_format = "glb"
                product.model_source = "procedural_python"
                product.model_status = "ready"
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    Base.metadata.create_all(bind=engine)
    seed_installation_services()
    seed_catalog_from_json_if_empty()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        # MVP: no global security requirement — call endpoints without Authorize.
    )
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if origins != ["*"] else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        """Render primary URL — send browsers to Swagger UI."""
        return RedirectResponse(url="/docs")

    prefix = settings.api_v1_prefix
    app.include_router(health.router, prefix=prefix)
    app.include_router(profile.router, prefix=prefix)
    app.include_router(products.router, prefix=prefix)
    app.include_router(assets.router, prefix=prefix)
    app.include_router(rooms.router, prefix=prefix)
    app.include_router(commerce.router, prefix=prefix)
    app.include_router(ai.router, prefix=prefix)
    return app


app = create_app()
