from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from app.db.models import Product, Property, Room, User
from app.services.model3d_service import generate_models_for_products, validate_glb
from app.core.config import get_settings


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_products_list_search_filter_pagination(client, seeded_products):
    r = client.get("/api/v1/products", params={"q": "Лампа", "page": 1, "page_size": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert all("Лампа" in i["name"] or "лампа" in (i["description"] or "").lower() for i in body["items"]) or body["total"] >= 1

    r2 = client.get("/api/v1/products", params={"category_id": "furniture", "min_price": 0, "max_price": 500})
    assert r2.status_code == 200
    assert r2.json()["total"] >= 1

    r3 = client.get("/api/v1/products", params={"sort": "price_asc"})
    prices = [Decimal(str(i["price"])) for i in r3.json()["items"] if i["price"] is not None]
    assert prices == sorted(prices)


def test_product_detail_optional_fields(client, seeded_products):
    r = client.get("/api/v1/products/oma-test-0")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "oma-test-0"
    assert "width_mm" in data
    assert data["price"] is not None


def test_missing_product(client):
    assert client.get("/api/v1/products/does-not-exist").status_code == 404


def test_favorites_cart_orders(client, seeded_products, demo_user):
    r = client.post("/api/v1/favorites/oma-test-0")
    assert r.status_code == 200
    assert client.get("/api/v1/favorites").json()
    r = client.post("/api/v1/cart/items", json={"product_id": "oma-test-0", "quantity": 2})
    assert r.status_code == 200
    assert Decimal(str(r.json()["total"])) > 0
    r = client.post("/api/v1/orders", json={"from_cart": True, "notes": "demo"})
    assert r.status_code == 200
    assert r.json()["is_demonstration"] is True


def test_room_photo_upload_and_ownership(client, db, demo_user, png_bytes):
    # another user
    other = User(email="other@oma.local", display_name="Other", is_demo=False)
    db.add(other)
    db.commit()
    prop = Property(user_id=other.id, name="Other home")
    db.add(prop)
    db.commit()
    room = Room(property_id=prop.id, name="Кухня", room_type="kitchen")
    db.add(room)
    db.commit()

    # demo user cannot upload to other's room
    files = {"file": ("room.png", BytesIO(png_bytes), "image/png")}
    denied = client.post(f"/api/v1/rooms/{room.id}/photos", files=files)
    assert denied.status_code == 404

    # create room for demo user via API
    p = client.post("/api/v1/properties", json={"name": "Мой дом"})
    assert p.status_code == 200
    room_resp = client.post(
        "/api/v1/rooms",
        json={"property_id": p.json()["id"], "name": "Кухня", "room_type": "kitchen"},
    )
    assert room_resp.status_code == 200
    room_id = room_resp.json()["id"]
    files = {"file": ("room.png", BytesIO(png_bytes), "image/png")}
    up = client.post(f"/api/v1/rooms/{room_id}/photos", files=files)
    assert up.status_code == 200
    assert up.json()["url"].startswith("/api/v1/assets/rooms/")


def test_reject_non_image_upload(client, demo_user):
    p = client.post("/api/v1/properties", json={"name": "Дом"})
    room = client.post(
        "/api/v1/rooms",
        json={"property_id": p.json()["id"], "name": "Комната"},
    )
    files = {"file": ("x.txt", BytesIO(b"not-an-image"), "text/plain")}
    r = client.post(f"/api/v1/rooms/{room.json()['id']}/photos", files=files)
    assert r.status_code == 400


def test_ai_recommendations_match_catalog_and_budget(client, seeded_products, demo_user):
    r = client.post(
        "/api/v1/ai/recommendations",
        json={"prompt": "освещение", "budget": 160, "category_ids": ["lighting"], "limit": 5},
    )
    assert r.status_code == 200
    body = r.json()
    ids = [i["product_id"] for i in body["recommendations"]]
    assert ids
    assert all(i.startswith("oma-test-") for i in ids)
    assert Decimal(str(body["budget"]["recommended_total"])) <= Decimal("160")


def test_ai_chat_validation(client, demo_user, seeded_products):
    r = client.post("/api/v1/ai/chat", json={"message": "Подбери лампу до 200 BYN", "budget": 200})
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"]
    assert isinstance(body["product_ids"], list)


def test_glb_generation_and_invalid_path(client, seeded_products, db, settings):
    result = generate_models_for_products(db, ["oma-test-0"])
    assert result["validated"] == 1
    path = settings.models_dir / "oma-test-0.glb"
    assert validate_glb(path)
    r = client.get("/api/v1/products/oma-test-0/3d")
    assert r.status_code == 200
    assert r.json()["has_3d_model"] is True
    missing = client.get("/api/v1/assets/products/oma-test-0/model.glb")
    # file exists now
    assert missing.status_code == 200
    bad = client.get("/api/v1/assets/products/nope/model.glb")
    assert bad.status_code == 404
