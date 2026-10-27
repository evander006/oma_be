from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import Category, Product, ProductImage, User
from app.db.session import get_db
from app.main import create_app


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    get_settings.cache_clear()
    s = get_settings()
    s.images_dir = tmp_path / "images"
    s.models_dir = tmp_path / "models"
    s.uploads_dir = tmp_path / "uploads"
    s.cache_dir = tmp_path / "cache"
    s.products_json_path = tmp_path / "products.json"
    s.images_dir.mkdir(parents=True, exist_ok=True)
    s.models_dir.mkdir(parents=True, exist_ok=True)
    s.uploads_dir.mkdir(parents=True, exist_ok=True)
    yield s
    get_settings.cache_clear()


@pytest.fixture()
def db_engine(settings):
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture()
def db(db_engine):
    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_engine, settings, monkeypatch):
    """Bind app engine/session to the isolated test database before lifespan runs."""
    import app.db.session as db_session
    import app.main as main_mod

    TestingSessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(db_session, "engine", db_engine)
    monkeypatch.setattr(db_session, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(main_mod, "engine", db_engine)
    monkeypatch.setattr(main_mod, "SessionLocal", TestingSessionLocal)

    app = create_app()

    def _override():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded_products(db):
    for cat_id, name, slug in (
        ("lighting", "Освещение", "osveshchenie"),
        ("furniture", "Мебель", "mebel"),
    ):
        if not db.get(Category, cat_id):
            # Avoid slug clash with lifespan seed categories.
            existing_slug = db.query(Category).filter(Category.slug == slug).first()
            if existing_slug:
                continue
            db.add(Category(id=cat_id, name=name, slug=slug))
    db.flush()
    # Prefer seeded category ids when present; else any matching slug.
    lighting = db.get(Category, "lighting") or db.query(Category).filter(
        Category.slug == "osveshchenie"
    ).first()
    furniture = db.get(Category, "furniture") or db.query(Category).filter(
        Category.slug.contains("mebel")
    ).first()
    lighting_id = lighting.id if lighting else None
    furniture_id = furniture.id if furniture else None

    products = []
    for i in range(3):
        existing = db.get(Product, f"oma-test-{i}")
        if existing:
            products.append(existing)
            continue
        p = Product(
            id=f"oma-test-{i}",
            name=f"Тестовый товар {i}",
            source_url=f"https://www.oma.by/test-{i}-p",
            category_id=lighting_id if i < 2 else furniture_id,
            price=Decimal("100") + i * 50,
            currency="BYN",
            description="Лампа для кухни" if i < 2 else "Стол",
            validation_status="validated",
            has_3d_model=False,
        )
        p.images.append(
            ProductImage(
                relative_path=f"images/products/{p.id}/00.jpg",
                sort_order=0,
                is_primary=True,
            )
        )
        products.append(p)
        db.add(p)
    db.commit()
    return products


@pytest.fixture()
def demo_user(db):
    from app.api.deps import get_or_create_demo_user

    return get_or_create_demo_user(db)


@pytest.fixture()
def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(120, 140, 160)).save(buf, format="PNG")
    return buf.getvalue()
