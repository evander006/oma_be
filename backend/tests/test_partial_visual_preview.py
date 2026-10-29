"""Regression: a stopped index has valid SKU rows despite incomplete manifest."""
from pathlib import Path
import json
import sqlite3
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import preview_partial_visual_index as preview


def test_stopped_index_uses_committed_rows_only(tmp_path, monkeypatch):
    root = tmp_path / "index"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({
        "model": preview.DEFAULT_MODEL,
        "complete": False, "indexed_count": 0,
        "catalog_count": 4, "dimensions": 2
    }), encoding="utf-8")
    np.save(root / "vectors.npy", np.array([
        [0.8, 0.6],
        [1.0, 0.0],  # A partially written vector with no committed SKU.
        [0.0, 0.0],
        [-1.0, 0.0],
    ], dtype=np.float16))
    with sqlite3.connect(root / "metadata.sqlite") as db:
        db.execute(
            "CREATE TABLE indexed_products (row_idx INTEGER PRIMARY KEY, "
            "sku TEXT, name TEXT, category_path TEXT, brand TEXT, image_url TEXT, price REAL)"
        )
        db.execute(
            "INSERT INTO indexed_products VALUES "
            "(0,'OMA-1','Настоящий товар','Инструменты','OMA','https://example.org/1.jpg',12.5)"
        )
        db.execute(
            "INSERT INTO indexed_products VALUES "
            "(3,'OMA-4','Другой товар','Инструменты','OMA','https://example.org/4.jpg',33.0)"
        )
    manifest, count = preview.read_index_status(root)
    assert count == 2
    assert manifest["indexed_count"] == 0
    monkeypatch.setattr(
        preview, "embed_image", lambda photo, model: np.array([1.0, 0.0], dtype=np.float32)
    )
    matches, count, total = preview.search_saved_partial_index(root, b"sample")
    assert count == 2
    assert total == 4
    assert [product["sku"] for product in matches] == ["OMA-1"]
    assert not any(product["sku"] == "OMA-2" for product in matches)
    assert json.loads((root / "manifest.json").read_text())["complete"] is False


def test_no_committed_rows_gives_readable_error(tmp_path):
    root = tmp_path / "index"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({
        "model": preview.DEFAULT_MODEL, "catalog_count": 1, "dimensions": 2
    }), encoding="utf-8")
    np.save(root / "vectors.npy", np.zeros((1, 2), dtype=np.float16))
    with sqlite3.connect(root / "metadata.sqlite") as db:
        db.execute("CREATE TABLE indexed_products (row_idx INTEGER PRIMARY KEY)")
    import pytest
    with pytest.raises(RuntimeError, match="нет сохранённых товаров"):
        preview.read_index_status(root)
