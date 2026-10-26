"""Catalog import and query helpers."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.db.models import Category, Product, ProductImage, ProductSpecification
from app.integrations.oma.parser import DEFAULT_CATEGORY_SEEDS


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def ensure_seed_categories(db: Session) -> None:
    for seed in DEFAULT_CATEGORY_SEEDS:
        existing = db.get(Category, seed["id"])
        if existing:
            continue
        db.add(
            Category(
                id=seed["id"],
                name=seed["name"],
                slug=seed["slug"],
                source_url=seed["url"],
            )
        )
    db.commit()


def upsert_products_from_json(db: Session, json_path: Path | None = None) -> dict[str, int]:
    settings = get_settings()
    path = json_path or settings.products_json_path
    if not path.is_file():
        raise FileNotFoundError(f"Products JSON not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    ensure_seed_categories(db)
    created = updated = 0
    for item in data:
        product = db.get(Product, item["id"])
        is_new = product is None
        if is_new:
            product = Product(id=item["id"])
            db.add(product)
            created += 1
        else:
            updated += 1
            db.query(ProductImage).filter(ProductImage.product_id == product.id).delete()
            db.query(ProductSpecification).filter(
                ProductSpecification.product_id == product.id
            ).delete()
            db.flush()

        product.source_product_id = item.get("source_product_id")
        product.sku = item.get("sku")
        product.name = item["name"]
        product.brand = item.get("brand")
        product.category_id = item.get("category_id")
        product.subcategory = item.get("subcategory")
        product.source_url = item["source_url"]
        product.description = item.get("description")
        price = item.get("price")
        product.price = Decimal(str(price)) if price is not None else None
        product.currency = item.get("currency") or settings.default_currency
        product.price_retrieved_at = _parse_dt(item.get("price_retrieved_at"))
        product.availability = item.get("availability")
        for dim in ("width_mm", "height_mm", "depth_mm", "diameter_mm", "weight_kg"):
            val = item.get(dim)
            setattr(product, dim, Decimal(str(val)) if val is not None else None)
        product.materials = item.get("materials")
        product.colors = item.get("colors")
        product.validation_status = item.get("validation_status") or "validated"
        product.source = item.get("source") or "oma.by"
        product.retrieved_at = _parse_dt(item.get("retrieved_at"))

        for idx, rel in enumerate(item.get("local_images") or []):
            filename = Path(rel).name
            product.images.append(
                ProductImage(
                    relative_path=f"images/products/{product.id}/{filename}",
                    source_url=(item.get("image_urls") or [None])[idx]
                    if idx < len(item.get("image_urls") or [])
                    else None,
                    sort_order=idx,
                    is_primary=idx == 0,
                )
            )
        seen_specs: set[str] = set()
        for spec in item.get("specifications") or []:
            name = (spec.get("name") or "").strip()
            if not name or name.lower() in seen_specs:
                continue
            seen_specs.add(name.lower())
            product.specifications.append(
                ProductSpecification(
                    name=name,
                    value=str(spec["value"]),
                    unit=spec.get("unit"),
                )
            )
    db.commit()
    return {"created": created, "updated": updated, "total": created + updated}


def list_products(
    db: Session,
    *,
    q: str | None = None,
    category_id: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    sort: str = "name",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Product], int]:
    query = db.query(Product).options(
        joinedload(Product.images),
        joinedload(Product.specifications),
        joinedload(Product.category),
    )
    filters = []
    if q:
        like = f"%{q}%"
        filters.append(or_(Product.name.ilike(like), Product.description.ilike(like)))
    if category_id:
        filters.append(Product.category_id == category_id)
    if min_price is not None:
        filters.append(Product.price >= min_price)
    if max_price is not None:
        filters.append(Product.price <= max_price)
    if filters:
        query = query.filter(and_(*filters))

    total = query.with_entities(func.count(Product.id)).scalar() or 0
    sort_map = {
        "name": Product.name.asc(),
        "price_asc": Product.price.asc(),
        "price_desc": Product.price.desc(),
        "newest": Product.created_at.desc(),
    }
    query = query.order_by(sort_map.get(sort, Product.name.asc()))
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, int(total)


def get_product(db: Session, product_id: str) -> Product | None:
    return (
        db.query(Product)
        .options(joinedload(Product.images), joinedload(Product.specifications))
        .filter(Product.id == product_id)
        .first()
    )


def filter_candidates_for_ai(
    db: Session,
    *,
    budget: Decimal | None,
    category_ids: list[str] | None,
    limit: int = 20,
) -> list[Product]:
    query = db.query(Product).options(joinedload(Product.images))
    if category_ids:
        query = query.filter(Product.category_id.in_(category_ids))
    if budget is not None:
        query = query.filter(or_(Product.price.is_(None), Product.price <= budget))
    return query.order_by(Product.price.asc().nulls_last(), Product.name.asc()).limit(limit).all()
