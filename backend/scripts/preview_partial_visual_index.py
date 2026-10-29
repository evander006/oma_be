#!/usr/bin/env python3
"""Try a saved, incomplete OMA photo index locally without changing any files in it.

Windows:
  .\.venv-vision\Scripts\python.exe backend\scripts\preview_partial_visual_index.py

A file picker opens when --image is omitted. The generated result HTML opens
in the default browser. Only catalogue product images use external URLs;
the query photograph stays on the computer.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import closing
from html import escape
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlsplit
import webbrowser

import numpy as np
from PIL import Image, ImageOps

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.full_catalog_visual import (  # noqa: E402
    DEFAULT_MODEL,
    embed_image,
    normalize,
    rank_rows,
)


def read_index_status(index_dir: Path) -> tuple[dict, int]:
    manifest_file = index_dir / "manifest.json"
    vector_file = index_dir / "vectors.npy"
    metadata_file = index_dir / "metadata.sqlite"
    for file in (manifest_file, vector_file, metadata_file):
        if not file.is_file():
            raise FileNotFoundError(f"Отсутствует файл индекса: {file}")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("model") != DEFAULT_MODEL:
        raise RuntimeError("Индекс создан для другой модели. Нельзя смешивать модели.")
    # The builder updates manifest.indexed_count only at the very end.
    # SQLite is committed each batch and therefore gives the REAL saved count.
    with closing(sqlite3.connect(f"{metadata_file.resolve().as_uri()}?mode=ro", uri=True)) as db:
        count = int(db.execute("SELECT COUNT(*) FROM indexed_products").fetchone()[0])
    if count == 0:
        raise RuntimeError("В metadata.sqlite ещё нет сохранённых товаров.")
    return manifest, count


def search_saved_partial_index(index_dir: Path, photo: bytes, limit: int = 10) -> tuple[list[dict], int, int]:
    """Read-only nearest-neighbour search over *committed* SKUs only.

    Unlike production search, this intentionally permits incomplete manifest.
    It does not change manifest.complete, vectors.npy or metadata.sqlite.
    """
    manifest, count = read_index_status(index_dir)
    vectors = np.load(index_dir / "vectors.npy", mmap_mode="r", allow_pickle=False)
    catalog_count = int(manifest["catalog_count"])
    dimensions = int(manifest["dimensions"])
    if vectors.shape != (catalog_count, dimensions):
        raise ValueError("Размеры векторов не совпадают с manifest.json")
    query = normalize(embed_image(photo, DEFAULT_MODEL))
    if query.size != dimensions:
        raise ValueError("Размерность фото не совпадает с индексом")

    # Read only rows that were durably committed before Ctrl+C, not
    # preallocated empty or half-written vectors.
    metadata: dict[int, dict] = {}
    best: list[tuple[int, float]] = []
    with closing(sqlite3.connect(
        f"{(index_dir / 'metadata.sqlite').resolve().as_uri()}?mode=ro", uri=True
    )) as db:
        cur = db.execute(
            "SELECT row_idx,sku,name,category_path,brand,image_url,price "
            "FROM indexed_products ORDER BY row_idx"
        )
        while True:
            batch = cur.fetchmany(2048)
            if not batch:
                break
            ids = [int(row[0]) for row in batch]
            if any(i < 0 or i >= catalog_count for i in ids):
                raise ValueError("В metadata.sqlite обнаружены недопустимые индексы")
            block = np.asarray(vectors[ids], dtype=np.float32)
            scores = block @ query
            for row, score in zip(batch, scores):
                if np.isfinite(score) and score > 0:
                    idx = int(row[0])
                    metadata[idx] = dict(zip(
                        ("sku", "name", "category_path", "brand", "image_url", "price"),
                        row[1:],
                    ))
                    best.append((idx, float(score)))
            # Keep a bounded list, discarding metadata for rows no longer needed.
            best.sort(key=lambda x: x[1], reverse=True)
            best = best[: max(240, limit)]
            survivors = {idx for idx, _ in best}
            metadata = {i: product for i, product in metadata.items() if i in survivors}

    # For an exploratory incomplete index use a generous threshold, and SHOW
    # cosine values rather than claiming they are exact-match probabilities.
    matches = rank_rows(best, metadata, terms=[], minimum_similarity=0.05, limit=limit)
    return matches, count, catalog_count


def _query_preview(photo_path: Path) -> str:
    with Image.open(photo_path) as src:
        photo = ImageOps.exif_transpose(src).convert("RGB")
        photo.thumbnail((480, 480))
        out = BytesIO()
        photo.save(out, format="JPEG", quality=78)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def create_html(matches: list[dict], count: int, total: int, photo_path: Path) -> str:
    cards = []
    for i, product in enumerate(matches, 1):
        url = str(product.get("image_url") or "")
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname:
            url = ""
        photo = (
            f'<img class="product" src="{escape(url, quote=True)}" alt="Фото товара ОМА">'
            if url else '<div class="noimg">Нет изображения</div>'
        )
        price = product.get("price_byn")
        price_text = f'{price:.2f} BYN' if isinstance(price, (float, int)) else "Цена не указана"
        cards.append(
            f'<article>{photo}<div><span class="rank">#{i}</span>'
            f'<h3>{escape(str(product["name"]))}</h3>'
            f'<p>{escape(str(product["category_path"]))}</p>'
            f'<p><b>Артикул:</b> {escape(str(product["sku"]))}</p>'
            f'<p>{escape(price_text)}</p>'
            f'<p class="similarity">Косинусная близость: {product["visual_similarity"]:.3f}</p>'
            '</div></article>'
        )
    items = "\n".join(cards) if cards else (
        '<p>Среди проиндексированных фотографий подходящих товаров не найдено.</p>'
    )
    percent = count / total * 100 if total else 0
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ОМА — пробный поиск по фото</title>
<style>
:root{{font-family:Arial,Helvetica,sans-serif;color:#262a2d;background:#f4f6f7}}
body{{max-width:850px;margin:30px auto;padding:0 16px}}
header{{background:#fff;border-radius:12px;padding:20px;display:flex;gap:18px;align-items:center}}
header img{{width:160px;max-height:160px;object-fit:contain;border-radius:8px}}
h1{{font-size:24px;margin:0 0 8px}}h3{{margin:4px 0 8px;font-size:17px}}
.subtitle,.similarity{{color:#626b75;font-size:13px}}
.warn{{background:#fff5db;padding:14px;border-radius:8px;margin:18px 0;font-size:14px}}
article{{display:flex;background:#fff;gap:16px;margin:12px 0;padding:14px;border-radius:10px}}
.product,.noimg{{width:145px;height:145px;object-fit:contain;flex-shrink:0}}
.rank{{color:#be1522;font-weight:bold}}p{{margin:6px 0;font-size:14px;line-height:1.45}}
@media(max-width:500px){{header{{display:block}}article{{gap:8px}}.product,.noimg{{width:100px;height:100px}}}}
</style></head><body><header>
<img src="{_query_preview(photo_path)}" alt="Тестовая фотография">
<div><h1>Поиск по фото · ОМА</h1>
<p>Сохранено <strong>{count:,}</strong> из <strong>{total:,}</strong> артикулов ({percent:.1f}%).</p>
<p class="subtitle">Локальный тест SigLIP2. Фотография не передаётся на сервер.</p></div></header>
<div class="warn"><strong>Тестовый частичный индекс.</strong> Поиск проверяет только {count:,}
 уже обработанных товаров. Необработанные товары не участвуют в выдаче.
 Косинусная близость — не вероятность точного совпадения артикула.</div>
{items}</body></html>'''


def choose_photo() -> Path:
    try:
        import tkinter as tk
        from tkinter import filedialog
        window = tk.Tk()
        window.withdraw()
        window.attributes("-topmost", True)
        selection = filedialog.askopenfilename(
            title="Выбери фотографию товара для поиска ОМА",
            filetypes=[("Фотографии", "*.jpg *.jpeg *.png *.webp *.bmp"), ("Все файлы", "*.*")],
        )
        window.destroy()
    except (ImportError, OSError, RuntimeError) as exc:
        raise RuntimeError("Не удалось открыть выбор фото. Укажи --image ПУТЬ_К_ФОТО") from exc
    if not selection:
        raise ValueError("Выбор фотографии отменён.")
    return Path(selection)


def main() -> None:
    parser = argparse.ArgumentParser(description="Локальная проверка сохранённого частичного индекса ОМА")
    parser.add_argument("--image", type=Path, help="Путь к фото. Если не указан — откроется окно выбора.")
    parser.add_argument("--index-dir", type=Path, default=BACKEND / "data" / "visual_index")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.limit <= 20:
        parser.error("--limit должен быть от 1 до 20")
    index_dir = args.index_dir.resolve()
    photo = (args.image if args.image is not None else choose_photo()).resolve()
    if not photo.is_file():
        parser.error(f"Фотография не найдена: {photo}")
    if photo.stat().st_size > 15 * 1024 * 1024:
        parser.error("Фотография больше 15 МБ; выбери уменьшенную версию.")
    print("Проверяем сохранённый индекс (без его изменения)...", flush=True)
    manifest, committed = read_index_status(index_dir)
    print(f"Сохранено SKU: {committed} / {manifest['catalog_count']}", flush=True)
    print("Загружаем SigLIP2 и сравниваем фотографию...", flush=True)
    matches, count, total = search_saved_partial_index(index_dir, photo.read_bytes(), args.limit)
    for i, product in enumerate(matches, 1):
        print(f"{i:>2}. {product['sku']} | {product['name']} | cosine={product['visual_similarity']:.3f}")
    if not matches:
        print("Совпадений в этой части каталога нет. Это не означает, что товара нет в ОМА.")
    output = BACKEND / "data" / "partial-photo-results.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(create_html(matches, count, total, photo), encoding="utf-8")
    print(f"Визуальный отчёт: {output}", flush=True)
    webbrowser.open(output.resolve().as_uri())


if __name__ == "__main__":
    main()
