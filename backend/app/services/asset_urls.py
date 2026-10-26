"""Build safe public asset URLs (never expose absolute server paths)."""
from __future__ import annotations

from app.core.config import get_settings
from app.db.models import Product, RoomPhoto
from app.schemas import Product3DOut, ProductImageOut, ProductOut, ProductSpecOut, RoomPhotoOut


def product_image_url(product_id: str, filename: str) -> str:
    settings = get_settings()
    prefix = settings.api_v1_prefix
    return f"{prefix}/assets/products/{product_id}/images/{filename}"


def product_model_url(product_id: str) -> str:
    settings = get_settings()
    return f"{settings.api_v1_prefix}/assets/products/{product_id}/model.glb"


def room_photo_url(room_id: int, filename: str) -> str:
    settings = get_settings()
    return f"{settings.api_v1_prefix}/assets/rooms/{room_id}/{filename}"


def serialize_product(product: Product, include_details: bool = True) -> ProductOut:
    images: list[ProductImageOut] = []
    primary = None
    for img in sorted(product.images, key=lambda i: (not i.is_primary, i.sort_order, i.id)):
        filename = img.relative_path.replace("\\", "/").split("/")[-1]
        url = product_image_url(product.id, filename)
        images.append(
            ProductImageOut(
                id=img.id,
                url=url,
                sort_order=img.sort_order,
                is_primary=img.is_primary,
                width=img.width,
                height=img.height,
            )
        )
        if img.is_primary and primary is None:
            primary = url
    if primary is None and images:
        primary = images[0].url

    model = None
    if include_details:
        model = Product3DOut(
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

    specs = []
    if include_details:
        specs = [
            ProductSpecOut(name=s.name, value=s.value, unit=s.unit)
            for s in product.specifications
        ]

    return ProductOut(
        id=product.id,
        source_product_id=product.source_product_id,
        sku=product.sku,
        name=product.name,
        brand=product.brand,
        category_id=product.category_id,
        subcategory=product.subcategory,
        source_url=product.source_url,
        description=product.description,
        price=product.price,
        currency=product.currency,
        price_retrieved_at=product.price_retrieved_at,
        availability=product.availability,
        width_mm=product.width_mm,
        height_mm=product.height_mm,
        depth_mm=product.depth_mm,
        diameter_mm=product.diameter_mm,
        weight_kg=product.weight_kg,
        materials=product.materials,
        colors=product.colors,
        validation_status=product.validation_status,
        has_3d_model=product.has_3d_model,
        primary_image_url=primary,
        images=images if include_details else images[:1],
        specifications=specs,
        model_3d=model,
    )


def serialize_room_photo(photo: RoomPhoto) -> RoomPhotoOut:
    filename = photo.relative_path.replace("\\", "/").split("/")[-1]
    return RoomPhotoOut(
        id=photo.id,
        room_id=photo.room_id,
        url=room_photo_url(photo.room_id, filename),
        original_filename=photo.original_filename,
        mime_type=photo.mime_type,
        width=photo.width,
        height=photo.height,
    )


def resolve_product_image_path(product_id: str, filename: str):
    settings = get_settings()
    safe_name = filename.replace("\\", "/").split("/")[-1]
    if ".." in safe_name or not safe_name:
        return None
    path = settings.images_dir / product_id / safe_name
    if not path.is_file():
        return None
    # Ensure path stays under images_dir
    try:
        path.resolve().relative_to(settings.images_dir.resolve())
    except ValueError:
        return None
    return path


def resolve_product_model_path(product_id: str):
    settings = get_settings()
    path = settings.models_dir / f"{product_id}.glb"
    if not path.is_file():
        return None
    try:
        path.resolve().relative_to(settings.models_dir.resolve())
    except ValueError:
        return None
    return path


def resolve_room_photo_path(room_id: int, filename: str):
    settings = get_settings()
    safe_name = filename.replace("\\", "/").split("/")[-1]
    if ".." in safe_name or not safe_name:
        return None
    path = settings.uploads_dir / "rooms" / str(room_id) / safe_name
    if not path.is_file():
        return None
    try:
        path.resolve().relative_to((settings.uploads_dir / "rooms").resolve())
    except ValueError:
        return None
    return path
