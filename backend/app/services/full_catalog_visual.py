"""Full OMA catalogue image-vector retrieval.

The index is built offline from the 134k-SKU Android SQLite catalogue.
No uploaded photographs or private data are retained. Without a complete
index (or optional ML runtime) the caller can use its existing fallback.
"""
from __future__ import annotations

from functools import lru_cache
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3

import numpy as np
from PIL import Image, ImageOps

DEFAULT_MODEL = "google/siglip2-base-patch16-224"
TOP_CANDIDATES = 240


def index_directory(data_dir: Path) -> Path:
    return Path(os.environ.get("OMA_VISUAL_INDEX_DIR", str(data_dir / "visual_index")))


@lru_cache(maxsize=2)
def _load_model(model_name: str):
    # The two large optional packages are imported only when a built index
    # exists; the ordinary API continues to run without PyTorch.
    import torch
    from transformers import AutoModel, AutoProcessor

    processor = AutoProcessor.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name).eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    return processor, model, device


def embed_image(photo: bytes, model_name: str) -> np.ndarray:
    import torch

    processor, model, device = _load_model(model_name)
    with Image.open(BytesIO(photo)) as opened:
        picture = ImageOps.exif_transpose(opened).convert("RGB")
        picture.thumbnail((1024, 1024))
        inputs = processor(images=[picture], return_tensors="pt")
    inputs = {key: tensor.to(device) for key, tensor in inputs.items()}
    with torch.inference_mode():
        result = model.get_image_features(**inputs)
    if not isinstance(result, torch.Tensor):
        result = getattr(result, "pooler_output", None)
    if result is None:
        raise RuntimeError("Visual model did not return an image embedding")
    vector = result[0].detach().float().cpu().numpy()
    return normalize(vector)


def normalize(vector: np.ndarray) -> np.ndarray:
    arr = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(arr))
    if not np.isfinite(norm) or norm <= 1e-9:
        raise ValueError("Invalid zero-length image vector")
    return arr / norm


def top_indices(vectors: np.ndarray, query: np.ndarray, count: int = TOP_CANDIDATES) -> list[tuple[int, float]]:
    """Exact cosine nearest neighbours with bounded working memory.

    Vectors are memory-mapped float16, and converted one 4096-row block
    at a time. This does not allocate a 400 MB float32 matrix on Render.
    """
    query = normalize(query)
    if len(vectors.shape) != 2 or vectors.shape[1] != query.size:
        raise ValueError("Vector index dimension differs from model")
    top: list[tuple[int, float]] = []
    for start in range(0, vectors.shape[0], 4096):
        block = np.asarray(vectors[start:start + 4096], dtype=np.float32)
        scores = block @ query
        size = min(count, scores.size)
        if size == 0:
            continue
        selected = np.argpartition(scores, -size)[-size:]
        top.extend((start + int(i), float(scores[i])) for i in selected if scores[i] > 0)
        top.sort(key=lambda pair: pair[1], reverse=True)
        del top[count:]
    return top


def text_agreement(name: str, category: str, terms: list[str]) -> float:
    """A small, *bounded* tie-breaker; vision stays the primary signal."""
    if not terms:
        return 0.0
    import re
    haystack = f"{name} {category}".casefold()
    stems = {
        token[:max(4, len(token) - 2)]
        for term in terms
        for token in re.findall(r"[а-яёa-z0-9]{4,}", term.casefold())
    }
    if not stems:
        return 0.0
    hits = sum(1 for stem in stems if stem in haystack)
    return min(1.0, hits / min(len(stems), 3))


def rank_rows(
    nearest: list[tuple[int, float]], metadata: dict[int, dict], terms: list[str],
    minimum_similarity: float = 0.15, limit: int = 12
) -> list[dict]:
    candidates = []
    for row_id, similarity in nearest:
        product = metadata.get(row_id)
        if not product or similarity < minimum_similarity:
            continue
        agreement = text_agreement(product["name"], product["category_path"], terms)
        # Terms are advisory: they can be wrong on unusual camera angles.
        score = 0.90 * similarity + 0.10 * agreement if terms else similarity
        candidates.append((score, similarity, product))
    candidates.sort(key=lambda row: (-row[0], -row[1], row[2]["sku"]))
    unique_skus: set[str] = set()
    matches = []
    for score, similarity, product in candidates:
        sku = product["sku"]
        if sku in unique_skus:
            continue
        unique_skus.add(sku)
        matches.append({
            "sku": sku,
            "product_id": sku,
            "name": product["name"],
            "category_path": product["category_path"],
            "brand": product["brand"],
            "image_url": product["image_url"],
            "price_byn": product["price"],
            "visual_similarity": round(similarity, 4),
            "match_score": round(score, 4),
            "match_type": "catalog_image_embedding",
            "is_exact_match": False,
        })
        if len(matches) >= limit:
            break
    return matches


def search_full_catalog(photo: bytes, terms: list[str], data_dir: Path) -> dict | None:
    """Return None only when the index is not available/usable.

    A complete index with zero qualifying matches returns an empty list
    rather than substituting unrelated products from a demo catalogue.
    """
    directory = index_directory(data_dir)
    manifest_path = directory / "manifest.json"
    vectors_path = directory / "vectors.npy"
    catalog_path = directory / "metadata.sqlite"
    if not all(p.is_file() for p in (manifest_path, vectors_path, catalog_path)):
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not manifest.get("complete") or not manifest.get("indexed_count"):
            return None
        model_name = manifest.get("model")
        if model_name != DEFAULT_MODEL:
            return None
        vectors = np.load(vectors_path, mmap_mode="r", allow_pickle=False)
        if vectors.shape != (int(manifest["catalog_count"]), int(manifest["dimensions"])):
            return None
        query = embed_image(photo, model_name)
        nearest = top_indices(vectors, query)
        if not nearest:
            return {"method": "siglip2_catalog_embeddings", "matches": [], "detected_objects": terms}
        ids = [idx for idx, _ in nearest]
        placeholders = ",".join("?" for _ in ids)
        with sqlite3.connect(f"file:{catalog_path}?mode=ro", uri=True) as db:
            rows = db.execute(
                f"SELECT row_idx,sku,name,category_path,brand,image_url,price "
                f"FROM indexed_products WHERE row_idx IN ({placeholders})", ids
            ).fetchall()
        metadata = {
            row[0]: dict(zip(("sku", "name", "category_path", "brand", "image_url", "price"), row[1:]))
            for row in rows
        }
        threshold = float(os.environ.get("OMA_VISUAL_MIN_COSINE", "0.15"))
        matches = rank_rows(nearest, metadata, terms, minimum_similarity=threshold)
        return {
            "method": "siglip2_catalog_embeddings",
            "detected_objects": terms,
            "matches": matches,
            "note": (
                "Сравнение с фотографиями полного индекса ОМА. "
                "Это похожие варианты, не подтверждение точного артикула."
                if matches else
                "Достаточно близкого товара на фотографии в индексе не найдено."
            ),
            "indexed_products": int(manifest["indexed_count"]),
            "price_note": "Цены из выгрузки; актуальность и наличие не подтверждены.",
        }
    except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error, ImportError) as exc:
        # Never make a running Android demonstration unavailable because
        # the optional vision index or model is missing/corrupt.
        import logging
        logging.getLogger(__name__).warning("Visual index unavailable: %s", exc)
        return None
