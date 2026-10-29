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


def test_scene_editor_route_serves_html(client):
    response = client.get("/api/v1/scene/editor")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "ОМА. Дом — 3D-квартира" in response.text
    assert "catalog-toggle" in response.text


def test_scene_excludes_unverified_legacy_placements(client, seeded_products, db):
    prop_id, room_id = _new_home(client)
    db.add(RoomPlacement(room_id=room_id, product_id=seeded_products[0].id))
    db.commit()
    scene = client.get(f"/api/v1/properties/{prop_id}/scene")
    assert scene.status_code == 200
    assert scene.json()["rooms"][0]["products"] == []



def test_unpurchased_catalog_items_can_be_saved_as_design_previews(client, seeded_products):
    prop_id, room_id = _new_home(client)
    product_id = seeded_products[2].id

    added = client.post(
        f"/api/v1/rooms/{room_id}/design-placements",
        json={
            "product_id": product_id,
            "pos_x": 1.1,
            "pos_y": 0.06,
            "pos_z": -0.7,
            "rotation_y": 1.2,
        },
    )
    assert added.status_code == 200, added.text
    assert added.json()["placement_type"] == "preview"
    assert added.json()["purchase_status"] == "design_preview"

    scene = client.get(f"/api/v1/properties/{prop_id}/scene").json()
    room = scene["rooms"][0]
    assert room["products"] == []
    assert [item["product_id"] for item in room["design_products"]] == [product_id]
    assert room["design_products"][0]["purchase_status"] == "design_preview"
    assert room["design_products"][0]["position"]["x"] == 1.1

    placement_id = added.json()["id"]
    updated = client.patch(
        f"/api/v1/rooms/{room_id}/design-placements/{placement_id}",
        json={"pos_x": -1.2, "pos_y": 0.06, "pos_z": 0.8, "rotation_y": 0.4},
    )
    assert updated.status_code == 200, updated.text
    refreshed = client.get(f"/api/v1/properties/{prop_id}/scene").json()
    assert refreshed["rooms"][0]["design_products"][0]["position"]["x"] == -1.2

    deleted = client.delete(
        f"/api/v1/rooms/{room_id}/design-placements/{placement_id}"
    )
    assert deleted.status_code == 200
    final_scene = client.get(f"/api/v1/properties/{prop_id}/scene").json()
    assert final_scene["rooms"][0]["design_products"] == []
    assert final_scene["rooms"][0]["products"] == []


def test_ordered_product_added_from_catalog_stays_in_owned_layer(client, seeded_products):
    prop_id, room_id = _new_home(client)
    product_id = seeded_products[0].id
    order = client.post(
        "/api/v1/orders", json={"product_ids": [product_id], "from_cart": False}
    )
    assert order.status_code == 200, order.text

    added = client.post(
        f"/api/v1/rooms/{room_id}/design-placements",
        json={"product_id": product_id, "pos_x": 0.5, "pos_y": 0.06, "pos_z": 0.3},
    )
    assert added.status_code == 200, added.text
    assert added.json()["placement_type"] == "owned"

    scene = client.get(f"/api/v1/properties/{prop_id}/scene").json()
    assert [item["product_id"] for item in scene["rooms"][0]["products"]] == [product_id]
    assert scene["rooms"][0]["design_products"] == []


def test_same_catalog_item_can_be_placed_more_than_once(client, seeded_products):
    prop_id, room_id = _new_home(client)
    product_id = seeded_products[2].id

    first = client.post(
        f"/api/v1/rooms/{room_id}/design-placements",
        json={"product_id": product_id, "pos_x": -0.8, "pos_y": 0.06, "pos_z": 0.2},
    )
    second = client.post(
        f"/api/v1/rooms/{room_id}/design-placements",
        json={"product_id": product_id, "pos_x": 0.8, "pos_y": 0.06, "pos_z": 0.2},
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] != second.json()["id"]

    scene = client.get(f"/api/v1/properties/{prop_id}/scene").json()
    previews = scene["rooms"][0]["design_products"]
    assert len(previews) == 2
    assert all(item["product_id"] == product_id for item in previews)


def test_generic_editor_route_serves_scene_shell(client):
    response = client.get("/api/v1/scene/editor")
    assert response.status_code == 200
    assert "OmaRoomBridge" in response.text
    assert "createRoom(info,index)" in response.text
