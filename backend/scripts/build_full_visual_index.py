#!/usr/bin/env python3
"""Build a resumable SigLIP2 image index from the FULL embedded OMA SQLite catalog.

Example (on a GPU workstation):
  pip install torch transformers sentencepiece httpx numpy Pillow
  python backend/scripts/build_full_visual_index.py \
    ../oma_front/android_companion/app/src/main/assets/embedded_catalog.db.bin \
    --output backend/data/visual_index

Copy the finished directory to the API host and set OMA_VISUAL_INDEX_DIR.
Never commit the large generated vectors or downloaded photographs to Git.
"""
from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import gzip
import hashlib
from io import BytesIO
from itertools import islice
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from threading import Lock
from urllib.parse import urlsplit

import httpx
import numpy as np
from PIL import Image, ImageOps

MODEL = "google/siglip2-base-patch16-224"
MAX_IMAGE_SIZE = 8 * 1024 * 1024
MIN_IMAGE_SIDE = 16  # 1x1 pixels and narrow banner images confuse image channel inference.
Image.MAX_IMAGE_PIXELS = 28_000_000


def _catalog_path(source: Path, temp: Path) -> Path:
    if source.suffix.lower() not in {".bin", ".gz"}:
        return source
    destination = temp / "catalog.db"
    with gzip.open(source, "rb") as src, destination.open("wb") as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)
    return destination


def _fingerprint(file: Path) -> str:
    digest = hashlib.sha256()
    with file.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _DownloadRateGate:
    """Share a conservative request rate across all download workers."""

    def __init__(self, minimum_spacing: float):
        self.minimum_spacing = minimum_spacing
        self._lock = Lock()
        self._next = 0.0

    def wait(self) -> None:
        if self.minimum_spacing <= 0:
            return
        with self._lock:
            now = time.monotonic()
            allowed_at = max(self._next, now)
            self._next = allowed_at + self.minimum_spacing
            delay = max(0.0, allowed_at - now)
        if delay:
            time.sleep(delay)


def fetch_product_image(
    client: httpx.Client, urls_json: str, request_delay: float = 0.15,
    request_gate: _DownloadRateGate | None = None,
) -> tuple[Image.Image, str] | None:
    try:
        urls = json.loads(urls_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(urls, list):
        return None
    for url in urls[:3]:
        if not isinstance(url, str):
            continue
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.hostname.lower() in {"localhost", "127.0.0.1"}:
            continue
        try:
            if request_gate is not None:
                request_gate.wait()
            chunks = bytearray()
            with client.stream("GET", url) as response:
                response.raise_for_status()
                if int(response.headers.get("content-length", 0)) > MAX_IMAGE_SIZE:
                    continue
                for chunk in response.iter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > MAX_IMAGE_SIZE:
                        break
            if len(chunks) > MAX_IMAGE_SIZE:
                continue
            with Image.open(BytesIO(chunks)) as original:
                picture = ImageOps.exif_transpose(original).convert("RGB")
                picture.thumbnail((1024, 1024))
                if min(picture.size) < MIN_IMAGE_SIDE:
                    # Product image feeds sometimes return 1x1 placeholders.
                    # They can crash the SigLIP2 preprocessing step with
                    # "Cannot handle this data type: (1, 1, 767), |u1".
                    picture.close()
                    continue
                return picture, url
        except (httpx.HTTPError, OSError, ValueError, Image.DecompressionBombError):
            continue
        finally:
            if request_gate is None and request_delay > 0:
                time.sleep(request_delay)
    return None


def _prefetched_images(client, source_rows, workers: int, request_delay: float):
    """Yield bounded, ordered downloads while overlapping network latency.

    No more than 2 * workers futures are in memory. Embeddings and database
    writes stay single-threaded, preserving crash-safe checkpoints.
    """
    if workers == 1:
        for row in source_rows:
            yield row, fetch_product_image(client, row[1][4], request_delay=request_delay)
        return

    gate = _DownloadRateGate(request_delay)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="oma-photo") as pool:
        queued = deque()

        def get_photo(row):
            return fetch_product_image(
                client, row[1][4], request_delay=request_delay, request_gate=gate
            )

        for row in source_rows:
            queued.append((row, pool.submit(get_photo, row)))
            if len(queued) >= workers * 2:
                queued_row, future = queued.popleft()
                yield queued_row, future.result()
        while queued:
            queued_row, future = queued.popleft()
            yield queued_row, future.result()


def _embed_batch(model, processor, device: str, images: list[Image.Image]) -> np.ndarray:
    import torch

    inputs = processor(images=images, return_tensors="pt")
    inputs = {key: value.to(device) for key, value in inputs.items()}
    with torch.inference_mode():
        result = model.get_image_features(**inputs)
    if not isinstance(result, torch.Tensor):
        result = getattr(result, "pooler_output", None)
    if result is None:
        raise RuntimeError("Vision encoder returned no embedding")
    matrix = result.detach().float().cpu().numpy()
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-9)
    return matrix


def _write_manifest(path: Path, data: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def build(
    source: Path, output: Path, batch_size: int, max_items: int,
    minimum_coverage: float, request_delay: float = 0.15,
    download_workers: int = 1,
) -> dict:
    from transformers import AutoModel, AutoProcessor
    import torch

    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="oma_visual_source_") as temp_dir:
        source_db = _catalog_path(source, Path(temp_dir))
        fingerprint = _fingerprint(source_db)
        # sqlite3.Connection.__exit__ commits/rolls back but DOES NOT close.
        # On Windows this otherwise leaves the temporary catalog.db locked.
        with closing(sqlite3.connect(source_db)) as catalog:
            total = catalog.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            if total < 1:
                raise ValueError("Source catalog is empty")
            inspected = min(max_items, total) if max_items else total
            processor = AutoProcessor.from_pretrained(MODEL)
            model = AutoModel.from_pretrained(MODEL).eval()
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model.to(device)
            dimension = int(_embed_batch(
                model, processor, device, [Image.new("RGB", (224, 224), "white")]
            ).shape[1])
            manifest_path = output / "manifest.json"
            vectors_path = output / "vectors.npy"
            meta_path = output / "metadata.sqlite"
            previous = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else None
            expected = {
                "model": MODEL,
                "source_sha256": fingerprint,
                "catalog_count": total,
                "dimensions": dimension,
            }
            if previous:
                if any(previous.get(key) != value for key, value in expected.items()):
                    raise ValueError("Index was created for another model/catalog; use a new output folder")
                if not vectors_path.exists() or not meta_path.exists():
                    raise ValueError("Incomplete index files; use a new output folder")
                vectors = np.load(vectors_path, mmap_mode="r+")
                if vectors.shape != (total, dimension):
                    raise ValueError("Index dimensions do not match manifest")
            else:
                if vectors_path.exists() or meta_path.exists():
                    raise ValueError("Existing index missing manifest; use a new output folder")
                vectors = np.lib.format.open_memmap(
                    vectors_path, "w+", dtype=np.float16, shape=(total, dimension)
                )
                _write_manifest(manifest_path, {**expected, "indexed_count": 0, "complete": False})
            metadata = sqlite3.connect(meta_path)
            try:
                metadata.execute(
                    "CREATE TABLE IF NOT EXISTS indexed_products("
                    "row_idx INTEGER PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL,"
                    "category_path TEXT NOT NULL, brand TEXT NOT NULL, image_url TEXT NOT NULL,"
                    "price REAL)"
                )
                processed = {row[0] for row in metadata.execute("SELECT row_idx FROM indexed_products")}
                pending: list[tuple[int, str, str, str, str, str, object, Image.Image]] = []
                missing_count = 0
                invalid_image_count = 0

                def flush() -> None:
                    nonlocal invalid_image_count
                    if not pending:
                        return
                    pixels = [row[7] for row in pending]
                    try:
                        accepted = []
                        try:
                            embeddings = _embed_batch(model, processor, device, pixels)
                            accepted = list(zip(pending, embeddings))
                        except (TypeError, ValueError, OSError) as exc:
                            # An unexpected malformed image must not abort a
                            # multi-hour 134k product indexing operation.
                            logging.warning(
                                "Batch of %d images failed preprocessing (%s); isolating each image.",
                                len(pending), exc
                            )
                            for product in pending:
                                try:
                                    single = _embed_batch(model, processor, device, [product[7]])
                                    accepted.append((product, single[0]))
                                except (TypeError, ValueError, OSError) as error:
                                    invalid_image_count += 1
                                    logging.warning(
                                        "Skipping invalid product photo (SKU %s): %s",
                                        product[1], error
                                    )
                            if not accepted:
                                raise RuntimeError(
                                    "Every image in the batch failed. Aborting rather than "
                                    "silently building a zero-product index."
                                ) from exc
                        for row, embedding in accepted:
                            vectors[row[0]] = embedding.astype(np.float16)
                        vectors.flush()  # Persist embeddings before recording rows as complete.
                        metadata.executemany(
                            "INSERT OR REPLACE INTO indexed_products VALUES(?,?,?,?,?,?,?)",
                            [(idx, sku, name, category, brand, image_url, price)
                             for (idx, sku, name, category, brand, image_url, price, _), _ in accepted]
                        )
                        metadata.commit()
                    finally:
                        for picture in pixels:
                            picture.close()
                        pending.clear()

                with httpx.Client(timeout=12.0, follow_redirects=True, headers={
                    "User-Agent": "OMA-visual-indexer/1.0"
                }) as client:
                    cursor = catalog.execute(
                        "SELECT sku,name,category_path,brand,image_urls,price "
                        "FROM products ORDER BY sku"
                    )
                    remaining = (
                        (idx, item)
                        for idx, item in enumerate(islice(cursor, inspected))
                        if idx not in processed
                    )
                    for (idx, (sku, name, category, brand, urls, price)), downloaded in (
                        _prefetched_images(client, remaining, download_workers, request_delay)
                    ):
                        if downloaded is None:
                            missing_count += 1
                            continue
                        picture, image_url = downloaded
                        try:
                            numeric_price = float(price) if price is not None else None
                        except (ValueError, TypeError):
                            numeric_price = None
                        pending.append((idx, str(sku), str(name), str(category), str(brand or ""),
                                        image_url, numeric_price, picture))
                        if len(pending) >= batch_size:
                            flush()
                        if (idx + 1) % 1000 == 0:
                            count = metadata.execute("SELECT COUNT(*) FROM indexed_products").fetchone()[0]
                            print(f"Scanned {idx + 1}/{inspected}: embedded {count}", flush=True)
                    flush()

                count = metadata.execute("SELECT COUNT(*) FROM indexed_products").fetchone()[0]
                coverage = count / total
                complete = inspected == total and coverage >= minimum_coverage
                summary = {
                    **expected, "indexed_count": count,
                    "coverage": round(coverage, 6), "complete": complete,
                    "image_download_failures_this_run": missing_count,
                    "invalid_image_embeddings_this_run": invalid_image_count,
                }
                _write_manifest(manifest_path, summary)
                return summary
            finally:
                metadata.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="embedded_catalog.db.bin or catalog.db")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument("--max-items", type=int, default=0, help="Smoke-test only; index remains incomplete")
    parser.add_argument("--minimum-coverage", type=float, default=0.80)
    parser.add_argument("--request-delay", type=float, default=0.15, help="Minimum gap between photo requests across workers (seconds)")
    parser.add_argument("--download-workers", type=int, default=1, help="Network-only parallel photo downloads, range 1..4")
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 64:
        parser.error("--batch-size must be in 1..64")
    if args.max_items < 0 or not 0 < args.minimum_coverage <= 1 or args.request_delay < 0:
        parser.error("Invalid item limit or coverage")
    if args.download_workers not in (1, 2, 3, 4):
        parser.error("--download-workers must be in 1..4")
    if args.download_workers > 1 and args.request_delay < 0.25:
        parser.error("Parallel photo downloads require --request-delay >= 0.25 (max 4 requests/sec)")
    summary = build(args.source.resolve(), args.output.resolve(),
                    args.batch_size, args.max_items, args.minimum_coverage,
                    args.request_delay, args.download_workers)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["complete"]:
        print("Index is not deployable yet. Retry indexing missing images or raise coverage.")


if __name__ == "__main__":
    main()
