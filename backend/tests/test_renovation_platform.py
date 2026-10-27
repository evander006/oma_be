from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from app.core.config import get_settings
from app.services.ai_capabilities import (
    UnavailableImageGenerationCapability,
    build_generation_prompt,
    get_ai_capabilities,
)
from app.services.loyalty_service import earn_points, get_or_create_account, redeem_points


def test_catalog_extra_filters(client, seeded_products, db):
    p = seeded_products[0]
    p.colors = "белый"
    p.materials = "металл"
    p.style_tags = "modern,minimal"
    p.room_types = "kitchen"
    p.width_mm = Decimal("400")
    db.commit()

    r = client.get("/api/v1/products", params={"color": "бел", "material": "металл"})
    assert r.status_code == 200
    assert r.json()["total"] >= 1

    r2 = client.get("/api/v1/products", params={"max_width_mm": 100})
    # Product with width 400 excluded; products with unknown width remain
    ids = [i["id"] for i in r2.json()["items"]]
    assert "oma-test-0" not in ids


def test_structured_room_analysis(client, demo_user, png_bytes, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "mock")
    get_settings.cache_clear()
    p = client.post("/api/v1/properties", json={"name": "Квартира"})
    room = client.post(
        "/api/v1/rooms",
        json={"property_id": p.json()["id"], "name": "Кухня", "room_type": "kitchen"},
    )
    room_id = room.json()["id"]
    files = {"file": ("room.png", BytesIO(png_bytes), "image/png")}
    assert client.post(f"/api/v1/rooms/{room_id}/photos", files=files).status_code == 200

    r = client.post(
        "/api/v1/ai/analyze-room",
        json={"room_id": room_id, "prompt": "Сделай светлее", "style": "минимализм"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body
    assert "uncertainties" in body
    assert body.get("id")


def test_design_session_generate_unavailable(client, demo_user, seeded_products, png_bytes, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("IMAGE_GEN_PROVIDER", "none")
    get_settings.cache_clear()

    p = client.post("/api/v1/properties", json={"name": "Дом"})
    room = client.post(
        "/api/v1/rooms",
        json={"property_id": p.json()["id"], "name": "Гостиная", "room_type": "living"},
    )
    room_id = room.json()["id"]
    files = {"file": ("room.png", BytesIO(png_bytes), "image/png")}
    client.post(f"/api/v1/rooms/{room_id}/photos", files=files)

    s = client.post(
        "/api/v1/ai/design-sessions",
        json={"room_id": room_id, "title": "Тест", "budget": 500},
    )
    assert s.status_code == 200
    sid = s.json()["id"]

    gen = client.post(
        f"/api/v1/ai/design-sessions/{sid}/generate",
        json={
            "product_ids": ["oma-test-0"],
            "instructions": "Добавь лампу",
            "idempotency_key": "idem-1",
        },
    )
    assert gen.status_code == 200
    body = gen.json()
    assert body["generation_status"] == "unavailable"
    assert body["retry_allowed"] is True
    assert body["visualization"]["status"] == "unavailable"
    # Selections preserved
    versions = client.get(f"/api/v1/ai/design-sessions/{sid}/versions").json()
    assert versions
    assert versions[0]["selected_products"][0]["product_id"] == "oma-test-0"


def test_design_session_mock_image_gen(client, demo_user, seeded_products, png_bytes, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("IMAGE_GEN_PROVIDER", "mock")
    get_settings.cache_clear()

    p = client.post("/api/v1/properties", json={"name": "Дом"})
    room = client.post(
        "/api/v1/rooms",
        json={"property_id": p.json()["id"], "name": "Спальня"},
    )
    room_id = room.json()["id"]
    files = {"file": ("room.png", BytesIO(png_bytes), "image/png")}
    client.post(f"/api/v1/rooms/{room_id}/photos", files=files)

    sid = client.post(
        "/api/v1/ai/design-sessions",
        json={"room_id": room_id},
    ).json()["id"]
    gen = client.post(
        f"/api/v1/ai/design-sessions/{sid}/generate",
        json={"product_ids": ["oma-test-1"], "instructions": "Стиль loft"},
    )
    assert gen.status_code == 200
    assert gen.json()["generation_status"] == "completed"


def test_image_gen_prompt_includes_product_ids():
    prompt = build_generation_prompt(
        instructions="поставить у окна",
        style="сканди",
        products=[{"id": "oma-1", "name": "Лампа", "width_mm": 200}],
    )
    assert "oma-1" in prompt
    assert "reference" in prompt.lower() or "Selected products" in prompt


def test_unavailable_image_capability():
    cap = UnavailableImageGenerationCapability()
    from app.services.ai_provider import AIImagePart

    result = cap.generate_visualization(
        room_image=AIImagePart(mime_type="image/jpeg", data=b"x"),
        product_references=[],
        prompt="test",
        product_meta=[],
    )
    assert result.status == "unavailable"


def test_renovation_project_and_estimate(client, demo_user, seeded_products):
    services = client.get("/api/v1/renovation/services")
    assert services.status_code == 200
    assert len(services.json()) >= 1
    service_id = services.json()[0]["id"]

    proj = client.post(
        "/api/v1/renovation/projects",
        json={
            "name": "Ремонт кухни",
            "scope": "turnkey",
            "area_m2": 12,
            "work_categories": ["кухня", "покраска"],
            "budget_max": 5000,
            "work_items": [
                {"service_id": service_id, "name": "Покраска", "quantity": 20, "unit": "м²"}
            ],
        },
    )
    assert proj.status_code == 200
    pid = proj.json()["id"]
    assert proj.json()["status"] == "draft"

    patched = client.patch(
        f"/api/v1/renovation/projects/{pid}",
        json={"status": "submitted"},
    )
    assert patched.json()["status"] == "submitted"

    req = client.post(
        "/api/v1/renovation/requests",
        json={"project_id": pid, "request_type": "turnkey", "submit": True},
    )
    assert req.status_code == 200
    assert "scheduling_note" in req.json()

    est = client.post(
        "/api/v1/renovation/estimates",
        json={
            "project_id": pid,
            "product_ids": ["oma-test-0"],
            "work_items": [{"service_id": service_id, "quantity": 10}],
        },
    )
    assert est.status_code == 200
    body = est.json()
    assert body["product_subtotal"] is not None
    assert "Предварительная" in body["disclaimer"] or body["disclaimer"]
    # Demo labor rates are unverified → incomplete or consultation
    assert body["status"] in {"preliminary", "incomplete", "consultation_required"}


def test_standalone_repair_request(client, demo_user):
    r = client.post(
        "/api/v1/renovation/requests",
        json={
            "request_type": "standalone",
            "notes": "Нужна замена смесителя",
            "payload": {"service": "plumbing"},
            "submit": True,
        },
    )
    assert r.status_code == 200
    assert r.json()["request_type"] == "standalone"
    got = client.get(f"/api/v1/renovation/requests/{r.json()['id']}")
    assert got.status_code == 200


def test_loyalty_earn_redeem_idempotency(client, demo_user, db):
    acc = client.get("/api/v1/loyalty/account")
    assert acc.status_code == 200
    assert acc.json()["is_development_config"] is True
    assert "demo" in acc.json()["program_label"].lower() or "development" in acc.json()[
        "program_label"
    ].lower()

    e1 = client.post(
        "/api/v1/loyalty/earn",
        json={"points": 100, "reason": "test", "idempotency_key": "earn-1"},
    )
    assert e1.status_code == 200
    assert e1.json()["balance"] == 100
    e2 = client.post(
        "/api/v1/loyalty/earn",
        json={"points": 100, "reason": "test", "idempotency_key": "earn-1"},
    )
    assert e2.json()["balance"] == 100  # idempotent

    bad = client.post(
        "/api/v1/loyalty/redeem",
        json={"points": 500, "reason": "too much", "idempotency_key": "red-1"},
    )
    assert bad.status_code == 400

    ok = client.post(
        "/api/v1/loyalty/redeem",
        json={"points": 40, "reason": "reward", "idempotency_key": "red-2"},
    )
    assert ok.status_code == 200
    assert ok.json()["balance"] == 60

    txs = client.get("/api/v1/loyalty/transactions")
    assert len(txs.json()) >= 2

    rewards = client.get("/api/v1/loyalty/rewards")
    assert rewards.status_code == 200
    assert rewards.json()


def test_loyalty_service_unit(db, demo_user):
    account = get_or_create_account(db, demo_user.id)
    assert account.balance == 0
    earn_points(
        db,
        user_id=demo_user.id,
        points=50,
        reason="unit",
        idempotency_key="u-earn",
    )
    redeem_points(
        db,
        user_id=demo_user.id,
        points=10,
        reason="unit",
        idempotency_key="u-red",
    )
    account = get_or_create_account(db, demo_user.id)
    assert account.balance == 40


def test_ai_capabilities_endpoint(client, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("IMAGE_GEN_PROVIDER", "none")
    get_settings.cache_clear()
    r = client.get("/api/v1/ai/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["vision_language"]["supports_image_input"] is True
    assert body["image_generation"]["supports_image_output"] is False


def test_project_ownership(client, demo_user, db):
    from app.db.models import User
    from app.db.models.renovation import RenovationProject

    other = User(email="other2@oma.local", display_name="X", is_demo=False)
    db.add(other)
    db.commit()
    project = RenovationProject(user_id=other.id, name="Чужой", status="draft")
    db.add(project)
    db.commit()

    r = client.get(f"/api/v1/renovation/projects/{project.id}")
    assert r.status_code == 404


def test_get_ai_capabilities_factory(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("IMAGE_GEN_PROVIDER", "none")
    get_settings.cache_clear()
    caps = get_ai_capabilities()
    assert caps.supports_image_input is True
    assert caps.supports_image_output is False
