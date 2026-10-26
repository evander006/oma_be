from __future__ import annotations

import json
from pathlib import Path

from app.integrations.oma.parser import OmaParser, ParsedProduct

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_product_from_fixture(tmp_path, monkeypatch):
    html = (FIXTURES / "product_sample.html").read_text(encoding="utf-8")
    settings_cache = tmp_path / "cache"
    settings_cache.mkdir()

    parser = OmaParser()
    # Bypass network: write into cache path used by parser for this URL
    url = "https://www.oma.by/sample-lamp-1-123456-p"
    cache_file = parser._cache_path(url)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(html, encoding="utf-8")

    product = parser.parse_product_page(url, category_id="lighting", subcategory="Лампы")
    assert isinstance(product, ParsedProduct)
    assert product.name
    assert product.sku == "1.123456"
    assert product.price == 79.9
    assert product.currency == "BYN"
    assert product.image_urls
    assert product.validation_status in {"validated", "incomplete"}
    parser.close()


def test_stable_id_idempotent():
    parser = OmaParser()
    a = parser._stable_id("https://oma.by/x-p", "1.1", "10")
    b = parser._stable_id("https://oma.by/x-p", "1.1", "10")
    assert a == b
    parser.close()


def test_duplicate_upsert(db, tmp_path, settings):
    from app.services.catalog_service import upsert_products_from_json

    payload = [
        {
            "id": "oma-dup-1",
            "source_product_id": "1",
            "sku": "1.1",
            "name": "Товар",
            "brand": "Brand",
            "category_id": "lighting",
            "subcategory": "Лампы",
            "source_url": "https://www.oma.by/dup-1-p",
            "description": "desc",
            "specifications": [{"name": "Цвет", "value": "белый", "unit": None}],
            "price": 10,
            "currency": "BYN",
            "availability": "InStock",
            "local_images": [],
            "image_urls": [],
            "validation_status": "validated",
            "retrieved_at": "2026-10-26T00:00:00+00:00",
            "price_retrieved_at": "2026-10-26T00:00:00+00:00",
        }
    ]
    path = settings.products_json_path
    path.write_text(json.dumps(payload), encoding="utf-8")
    from app.db.models import Category

    db.add(Category(id="lighting", name="Освещение", slug="osveshchenie"))
    db.commit()
    first = upsert_products_from_json(db, path)
    second = upsert_products_from_json(db, path)
    assert first["created"] == 1
    assert second["updated"] == 1
    assert second["created"] == 0
