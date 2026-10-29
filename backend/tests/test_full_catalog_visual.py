"""Fast deterministic tests: no model downloads, network or GPU required."""
import json
import sqlite3

import numpy as np

from app.services import full_catalog_visual as visual


def test_chunked_nearest_neighbour_search_uses_image_content():
    matrix = np.zeros((8200, 3), dtype=np.float16)
    matrix[0] = [0, 1, 0]
    matrix[4100] = [1, 0, 0]
    matrix[8199] = [0.5, 0.5, 0]
    ranked = visual.top_indices(matrix, np.array([1, 0, 0]), count=3)
    assert ranked[0][0] == 4100
    assert ranked[0][1] > ranked[1][1]
    assert len(ranked) == 2  # zero vectors are not product matches


def test_ranked_results_are_grounded_in_metadata_not_invented():
    details = {
        1: dict(sku="OMA-1", name="Смеситель чёрный", category_path="Сантехника",
                brand="ОМA", image_url="https://example.org/1.jpg", price=10.0),
        2: dict(sku="OMA-1", name="Смеситель чёрный", category_path="Сантехника",
                brand="ОМA", image_url="https://example.org/1.jpg", price=10.0),
        3: dict(sku="OMA-2", name="Лопата", category_path="Инструмент",
                brand="", image_url="https://example.org/2.jpg", price=5.0),
    }
    scored = visual.rank_rows([(3, 0.91), (1, 0.90), (2, 0.85)], details, ["смеситель"])
    assert scored[0]["sku"] == "OMA-1"
    assert len({row["sku"] for row in scored}) == len(scored)
    assert all(not row["is_exact_match"] for row in scored)
    assert visual.rank_rows([(3, 0.1)], details, [], minimum_similarity=0.15) == []


def test_complete_index_resolves_real_sku_and_empty_match_does_not_use_demo_catalog(
    tmp_path, monkeypatch
):
    root = tmp_path / "index"
    root.mkdir()
    db = sqlite3.connect(root / "metadata.sqlite")
    db.execute(
        "CREATE TABLE indexed_products("
        "row_idx INTEGER PRIMARY KEY,sku TEXT,name TEXT,category_path TEXT,"
        "brand TEXT,image_url TEXT,price REAL)"
    )
    db.execute(
        "INSERT INTO indexed_products VALUES(0,'OMA-123','Чёрный смеситель',"
        "'Сантехника','OMA','https://example.org/product.jpg',12.5)"
    )
    db.commit()
    db.close()
    np.save(root / "vectors.npy", np.array([[1.0, 0.0]], dtype=np.float16))
    (root / "manifest.json").write_text(json.dumps({
        "model": visual.DEFAULT_MODEL, "complete": True,
        "indexed_count": 1, "catalog_count": 1, "dimensions": 2
    }), encoding="utf-8")
    monkeypatch.setenv("OMA_VISUAL_INDEX_DIR", str(root))
    monkeypatch.setattr(
        visual, "embed_image", lambda photo, model: np.array([1.0, 0.0], dtype=np.float32)
    )
    result = visual.search_full_catalog(b"image", ["смеситель"], tmp_path)
    assert result["method"] == "siglip2_catalog_embeddings"
    assert result["matches"][0]["sku"] == "OMA-123"
    assert result["matches"][0]["price_byn"] == 12.5
    monkeypatch.setattr(
        visual, "embed_image", lambda photo, model: np.array([-1.0, 0.0], dtype=np.float32)
    )
    result = visual.search_full_catalog(b"image", [], tmp_path)
    assert result is not None
    assert result["matches"] == []


def test_missing_or_incomplete_index_keeps_existing_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("OMA_VISUAL_INDEX_DIR", str(tmp_path))
    assert visual.search_full_catalog(b"image", [], tmp_path) is None


def test_index_status_reports_missing_files_without_claiming_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("OMA_VISUAL_INDEX_DIR", str(tmp_path))
    status = visual.index_status(tmp_path)
    assert status["ready"] is False
    assert status["reason"] == "full_catalog_index_not_installed"
    assert status["indexed_products"] == 0
