"""3D must contain only explicitly ordered and linked OMA goods."""
from app.db.models import OrderItem, Property, Room, RoomPlacement


def _new_home(client):
    p = client.post("/api/v1/properties", json={
        "name": "Тестовая квартира", "property_type": "apartment"
    })
    assert p.status_code == 200, p.text
    r = client.post("/api/v1/rooms", json={
        "property_id": p.json()["id"], "name": "Кухня",
        "room_type": "kitchen", "width_m": 4.2, "length_m": 5.1
    })
    assert r.status_code == 200, r.text
    return p.json()["id"], r.json()["id"]


def test_scene_has_rooms_but_never_invents_purchases(client, seeded_products):
    prop_id, room_id = _new_home(client)
    scene = client.get(f"/api/v1/properties/{prop_id}/scene")
    assert scene.status_code == 200, scene.text
    assert scene.json()["rooms"][0]["products"] == []
    assert scene.json()["rooms"][0]["dimensions_confirmed"] is False
    blocked = client.post(
        f"/api/v1/rooms/{room_id}/placements",
        params={"product_id": seeded_products[0].id},
    )
    assert blocked.status_code == 409
    assert client.get("/api/v1/properties/999999/scene").status_code == 404


def test_only_ordered_and_explicitly_placed_products_appear(
    client, seeded_products
):
    prop_id, room_id = _new_home(client)
    product_id = seeded_products[0].id
    other_id = seeded_products[1].id
    order = client.post("/api/v1/orders", json={
        "product_ids": [product_id], "from_cart": False,
    })
    assert order.status_code == 200, order.text
    assert order.json()["is_demonstration"] is True
    empty = client.get(f"/api/v1/properties/{prop_id}/scene")
    assert empty.json()["rooms"][0]["products"] == []

    response = client.post(
        f"/api/v1/rooms/{room_id}/placements", params={"product_id": product_id}
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_demo"] is True
    repeat = client.post(
        f"/api/v1/rooms/{room_id}/placements", params={"product_id": product_id}
    )
    assert repeat.status_code == 200
    assert repeat.json()["id"] == response.json()["id"]

    denied = client.post(
        f"/api/v1/rooms/{room_id}/placements", params={"product_id": other_id}
    )
    assert denied.status_code == 409
    scene = client.get(f"/api/v1/properties/{prop_id}/scene")
    goods = scene.json()["rooms"][0]["products"]
    assert [item["product_id"] for item in goods] == [product_id]
    assert goods[0]["purchase_status"] == "demonstration_order"
    assert goods[0]["is_demo"] is True


def test_scene_excludes_unverified_legacy_placements(client, seeded_products, db):
    prop_id, room_id = _new_home(client)
    db.add(RoomPlacement(room_id=room_id, product_id=seeded_products[0].id))
    db.commit()
    scene = client.get(f"/api/v1/properties/{prop_id}/scene")
    assert scene.status_code == 200
    assert scene.json()["rooms"][0]["products"] == []
