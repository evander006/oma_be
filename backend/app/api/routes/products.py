from decimal import Decimal
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.models import Category
from app.db.session import get_db
from app.schemas import CategoryOut, Page, Product3DOut, ProductImageOut, ProductOut
from app.services.asset_urls import product_model_url, serialize_product
from app.services.catalog_service import get_product, list_products

router = APIRouter(tags=["catalog"])


@router.get("/products", response_model=Page[ProductOut])
def products(
    q: str | None = None,
    category_id: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    sort: str = Query(default="name"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[ProductOut]:
    items, total = list_products(
        db,
        q=q,
        category_id=category_id,
        min_price=min_price,
        max_price=max_price,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    pages = ceil(total / page_size) if page_size else 0
    return Page(
        items=[serialize_product(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/products/{product_id}", response_model=ProductOut)
def product_detail(product_id: str, db: Session = Depends(get_db)) -> ProductOut:
    product = get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return serialize_product(product)


@router.get("/products/{product_id}/images", response_model=list[ProductImageOut])
def product_images(product_id: str, db: Session = Depends(get_db)) -> list[ProductImageOut]:
    product = get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return serialize_product(product).images


@router.get("/products/{product_id}/3d", response_model=Product3DOut)
def product_3d(product_id: str, db: Session = Depends(get_db)) -> Product3DOut:
    product = get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return Product3DOut(
        product_id=product.id,
        has_3d_model=product.has_3d_model,
        url=product_model_url(product.id) if product.has_3d_model else None,
        format=product.model_format,
        source=product.model_source,
        status=product.model_status,
        limitations=product.model_limitations,
        width=product.model_width_m,
        height=product.model_height_m,
        depth=product.model_depth_m,
        units=product.model_units or "m",
    )


@router.get("/categories", response_model=list[CategoryOut])
def categories(db: Session = Depends(get_db)) -> list[Category]:
    return db.query(Category).order_by(Category.name.asc()).all()


@router.get("/categories/{category_id}/products", response_model=Page[ProductOut])
def category_products(
    category_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[ProductOut]:
    if not db.get(Category, category_id):
        raise HTTPException(status_code=404, detail="Category not found")
    items, total = list_products(
        db, category_id=category_id, page=page, page_size=page_size
    )
    pages = ceil(total / page_size) if page_size else 0
    return Page(
        items=[serialize_product(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )
