#!/usr/bin/env python3
"""LAN-only OMA hackathon image-search API backed by the *saved partial* index.

Start on Windows:
  .\.venv-vision\Scripts\python.exe backend\scripts\serve_partial_visual_api.py

Connect the DEBUG APK's photo-search URL to http://<PC-LAN-IP>:8765.
Use only on a private trusted Wi-Fi network. No public port forwarding.
No upload persistence, no full backend needed.
"""
from __future__ import annotations

import argparse
import asyncio
from io import BytesIO
import logging
from pathlib import Path
import sys

from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool
import uvicorn

from preview_partial_visual_index import read_index_status, search_saved_partial_index

logger = logging.getLogger("oma.partial")
MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 28_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def validate_upload(raw: bytes) -> bytes:
    if not raw:
        raise ValueError("Пустое изображение")
    if len(raw) > MAX_BYTES:
        raise ValueError("Фотография превышает 8 МБ")
    try:
        with Image.open(BytesIO(raw)) as src:
            if src.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Допускаются JPEG, PNG и WEBP")
            if src.width < 16 or src.height < 16:
                raise ValueError("Изображение слишком маленькое")
            if src.width * src.height > MAX_PIXELS:
                raise ValueError("Изображение слишком большое")
            picture = ImageOps.exif_transpose(src).convert("RGB")
            picture.thumbnail((1024, 1024))
            with BytesIO() as output:
                picture.save(output, format="JPEG", quality=82)
                return output.getvalue()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError("Не удалось прочитать фотографию") from exc


def create_app(index_dir: Path) -> FastAPI:
    app = FastAPI(
        title="OMA local partial image search",
        description="Demo-only LAN photo search. Do not expose this API to the internet.",
    )
    # Only one GPU inference at a time, avoiding two phones exhausting a 6 GB laptop GPU.
    gpu_gate = asyncio.Semaphore(1)

    @app.get("/api/v1/visual-search/status")
    def status() -> dict:
        manifest, count = read_index_status(index_dir)
        return {
            "ready": True,
            "method": "siglip2_catalog_embeddings",
            "indexed_products": count,
            "catalog_products": int(manifest["catalog_count"]),
            "partial_index": not bool(manifest.get("complete", False)),
            "note": "Локальный пробный индекс, только товары с готовыми векторами.",
        }

    @app.post("/api/v1/visual-search")
    async def visual_search(file: UploadFile = File(...)) -> dict:
        if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise HTTPException(status_code=415, detail="Нужна фотография JPEG/PNG/WEBP")
        try:
            raw = await file.read(MAX_BYTES + 1)
        finally:
            await file.close()
        if len(raw) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="Файл больше 8 МБ")
        try:
            prepared = await run_in_threadpool(validate_upload, raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        async with gpu_gate:
            try:
                matches, count, total = await run_in_threadpool(
                    search_saved_partial_index, index_dir, prepared, 12
                )
            except (OSError, ValueError, RuntimeError) as exc:
                logger.exception("Local image search failed: %s", exc)
                raise HTTPException(status_code=503, detail="Ошибка локального поиска") from exc

        return {
            "method": "siglip2_catalog_embeddings",
            "matches": matches,
            "detected_objects": [],
            "indexed_products": count,
            "catalog_products": total,
            "partial_index": True,
            "note": (
                f"Пробный визуальный поиск среди {count} из {total} товаров ОМА. "
                "Найденные варианты — не гарантия точного артикула."
            ),
        }

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Local demo API for incomplete OMA visual indexes")
    parser.add_argument("--index-dir", type=Path, default=(
        Path(__file__).resolve().parents[1] / "data" / "visual_index"
    ))
    parser.add_argument("--host", default="0.0.0.0", help="LAN binding; never use port forwarding")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    index_dir = args.index_dir.resolve()
    manifest, count = read_index_status(index_dir)
    print(
        f"OMA SigLIP2 demo: {count} saved SKU / {manifest['catalog_count']} total. "
        f"Listening on {args.host}:{args.port}. Do NOT expose to the internet.",
        flush=True
    )
    uvicorn.run(create_app(index_dir), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
