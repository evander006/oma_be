"""Photo-to-catalog search for jury demos.

Uses the configured vision model if credentials are present, otherwise computes
*actual* color-histogram similarity to real downloaded catalog images.
The color-only fallback is deliberately labelled and never claims object
recognition or an exact match. User photographs are processed in memory.
"""
from __future__ import annotations

from io import BytesIO
from functools import lru_cache
import math
from pathlib import Path
import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Product
from app.db.session import get_db
from app.services.ai_provider import AIImagePart, AIProviderError, get_ai_provider
from app.services.asset_urls import resolve_product_image_path, serialize_product
from app.services.full_catalog_visual import search_full_catalog

router = APIRouter(tags=["visual-search"])
Image.MAX_IMAGE_PIXELS = 28_000_000
ALLOWED = {"JPEG", "PNG", "WEBP"}


def image_features(data: bytes) -> tuple[float, ...]:
    """Return a compact foreground-aware colour and shape descriptor.

    The first twelve values preserve the old RGB histogram contract.  The
    remaining values capture coarse spatial luminance and edge density, which
    stops similarly-coloured but differently-shaped products from dominating
    the offline fallback.
    """
    try:
        with Image.open(BytesIO(data)) as original:
            if original.format not in ALLOWED:
                raise ValueError("Unsupported image format")
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail((96, 96))
            image = ImageOps.fit(image, (96, 96), method=Image.Resampling.LANCZOS)
            pixels = list(image.getdata())
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError("Invalid JPEG, PNG or WEBP image") from exc
    bins = [0.0] * 12
    count = 0
    for r, g, b in pixels:
        # Ignore nearly white catalog backgrounds / room walls where possible.
        if min(r, g, b) > 245:
            continue
        for index, component in enumerate((r, g, b)):
            bins[index * 4 + min(component // 64, 3)] += 1
        count += 1
    if count == 0:
        return tuple([0.0] * 22)
    histogram = [value / count for value in bins]
    gray = image.convert("L")
    spatial: list[float] = []
    for gy in range(3):
        for gx in range(3):
            crop = gray.crop((gx * 32, gy * 32, (gx + 1) * 32, (gy + 1) * 32))
            spatial.append(sum(crop.getdata()) / (32 * 32 * 255.0))
    edges = 0.0
    samples = 0
    px = gray.load()
    for y in range(1, 95, 2):
        for x in range(1, 95, 2):
            edges += abs(px[x, y] - px[x - 1, y]) + abs(px[x, y] - px[x, y - 1])
            samples += 2
    return tuple(histogram + spatial + [edges / max(1.0, samples * 255.0)])


def feature_similarity(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    if not any(first) or not any(second):
        return 0.0
    # Colour remains important for product photos, while shape/spatial content
    # disambiguates e.g. a red drill from a red bucket.
    color = sum(min(a, b) for a, b in zip(first[:12], second[:12])) / 3.0
    tail_a, tail_b = first[12:], second[12:]
    dot = sum(a * b for a, b in zip(tail_a, tail_b))
    norm = math.sqrt(sum(a * a for a in tail_a) * sum(b * b for b in tail_b))
    shape = dot / norm if norm else 0.0
    return max(0.0, min(1.0, color * 0.72 + shape * 0.28))


@lru_cache(maxsize=4096)
def _catalog_features(path: str, modified_ns: int) -> tuple[float, ...]:
    """Cache descriptors while still invalidating when an image is replaced."""
    del modified_ns
    return image_features(Path(path).read_bytes())


def _vision_terms(data: bytes) -> list[str]:
    settings = get_settings()
    configured = (
        (settings.ai_provider == "openrouter" and settings.openrouter_api_key)
        or (settings.ai_provider == "gemini" and settings.gemini_api_key)
        or (settings.ai_provider == "nvidia" and settings.nvidia_api_key)
    )
    if not configured:
        return []
    try:
        provider = get_ai_provider()
        result = provider.generate(
            system_prompt=(
                "Ты распознаёшь товары для магазина стройматериалов. "
                "Верни только JSON: {\"objects\":[\"смеситель\",\"светильник\"]}. "
                "Укажи до пяти визуально распознаваемых объектов; не придумывай SKU, цену и бренд."
            ),
            user_text="Какие товары видны на изображении? Назови категории предметов на русском.",
            images=[AIImagePart(mime_type="image/jpeg", data=data)],
            expect_json=True,
        )
        result_dict = result.structured or {}
        terms = result_dict.get("objects", [])
        return [str(t).strip().casefold() for t in terms[:5] if str(t).strip()] if isinstance(terms, list) else []
    except (AIProviderError, ValueError, KeyError, TypeError):
        return []


def _match_text(product: Product, terms: list[str]) -> int:
    if not terms:
        return 0
    haystack = " ".join(
        x for x in (product.name, product.subcategory, product.colors, product.description)
        if isinstance(x, str)
    ).casefold()
    score = 0
    for phrase in terms:
        if phrase in haystack:
            score += 4
        for token in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", phrase):
            stem = token[:max(4, len(token) - 3)]
            if stem in haystack:
                score += 2
    return score


@router.post("/visual-search")
async def visual_search(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_settings()
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Загрузите JPEG, PNG или WEBP")
    data = await file.read(settings.max_upload_bytes + 1)
    await file.close()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Изображение слишком большое")
    if not data:
        raise HTTPException(status_code=400, detail="Файл пуст")

    try:
        query_features = image_features(data)
        with Image.open(BytesIO(data)) as src:
            converted = ImageOps.exif_transpose(src).convert("RGB")
            converted.thumbnail((1024, 1024))
            buf = BytesIO()
            converted.save(buf, "JPEG", quality=82)
            vision_bytes = buf.getvalue()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=400, detail="Невозможно прочитать изображение") from exc

    terms = _vision_terms(vision_bytes)
    # The full Android catalogue index takes precedence over the small backend demo DB.
    # A complete index returning zero matches must NOT fall back to unrelated items.
    full_catalog = search_full_catalog(vision_bytes, terms, settings.data_dir)
    if full_catalog is not None:
        return full_catalog
    products = db.query(Product).all()
    scored = []
    for product in products:
        if not product.images:
            continue
        chosen = min(product.images, key=lambda img: (not img.is_primary, img.sort_order))
        path = resolve_product_image_path(product.id, Path(chosen.relative_path).name)
        if path is None:
            continue
        try:
            # The search is grounded in actual catalog image files.
            stat = path.stat()
            similarity = feature_similarity(
                query_features, _catalog_features(str(path), stat.st_mtime_ns)
            )
        except (OSError, ValueError):
            continue
        text_score = _match_text(product, terms)
        if not terms and similarity < 0.12:
            continue
        # Vision category semantics lead; real catalogue pixels break ties and
        # keep useful candidates when the model uses an unexpected synonym.
        semantic = min(1.0, text_score / 8.0)
        score = (semantic * 0.78 + similarity * 0.22) if terms else similarity
        scored.append((score, similarity, product))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2].name))

    matches = []
    for score, similarity, product in scored[:12]:
        dto = serialize_product(product, include_details=False)
        matches.append({
            "product_id": product.id,
            "sku": product.sku,
            "name": product.name,
            "price_byn": float(product.price) if product.price is not None else None,
            "image_url": dto.primary_image_url,
            "visual_color_similarity": round(similarity, 3),
            "match_score": round(score, 3),
            "match_type": "possible_category_match" if terms else "visual_color_similarity",
            "is_exact_match": False,
        })
    return {
        "method": "vision_category_plus_color" if terms else "local_color_histogram",
        "detected_objects": terms,
        "matches": matches,
        "note": (
            "Категории определены vision-моделью; найденные товары не являются точными совпадениями."
            if terms else
            "ИИ-анализ недоступен: результаты отсортированы только по сходству цветов "
            "с фотографиями каталога, а не по распознаванию предметов."
        ),
        "price_note": "Цены — исторический снимок каталога; наличие и актуальность не подтверждены.",
    }
