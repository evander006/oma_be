from __future__ import annotations


def _home(client):
    prop = client.post(
        "/api/v1/properties",
        json={
            "name": "Квартира Анны",
            "address": "Минск, демонстрационный адрес",
            "property_type": "apartment",
            "tenure": "rented",
        },
    )
    assert prop.status_code == 200, prop.text
    room = client.post(
        "/api/v1/rooms",
        json={
            "property_id": prop.json()["id"],
            "name": "Гостиная",
            "room_type": "living",
            "width_m": 4.2,
            "length_m": 5.1,
            "wall_material": "штукатурка",
            "floor_material": "ламинат",
        },
    )
    assert room.status_code == 200, room.text
    return prop.json(), room.json()


def test_home_passport_patch_equipment_and_history(client, seeded_products):
    prop, room = _home(client)
    patched = client.patch(
        f"/api/v1/properties/{prop['id']}",
        json={"name": "Моя квартира", "tenure": "rented"},
    )
    assert patched.status_code == 200
    assert patched.json()["tenure"] == "rented"

    patched_room = client.patch(
        f"/api/v1/rooms/{room['id']}",
        json={"ceiling_material": "краска", "height_m": 2.7},
    )
    assert patched_room.status_code == 200
    assert patched_room.json()["ceiling_material"] == "краска"

    added = client.post(
        f"/api/v1/properties/{prop['id']}/equipment",
        json={
            "room_id": room["id"],
            "product_id": seeded_products[0].id,
            "name": "Настольная лампа",
            "specifications": {"мощность": "10 Вт"},
        },
    )
    assert added.status_code == 201, added.text
    assert added.json()["product_snapshot"]["id"] == seeded_products[0].id

    equipment = client.get(
        f"/api/v1/properties/{prop['id']}/equipment", params={"room_id": room["id"]}
    )
    assert equipment.status_code == 200
    assert len(equipment.json()) == 1
    history = client.get(f"/api/v1/properties/{prop['id']}/history")
    assert history.status_code == 200
    assert history.json()[0]["event_type"] == "equipment_added"


def test_contractor_work_order_proposal_completion_flow(client, seeded_products):
    prop, room = _home(client)
    contractors = client.get("/api/v1/contractors", params={"specialty": "элект"})
    assert contractors.status_code == 200
    assert contractors.json()
    contractor = contractors.json()[0]
    assert contractor["is_demo"] is True
    assert contractor["rating"] is None
    assert contractor["reviews"] == []

    favorite = client.post(f"/api/v1/contractors/{contractor['id']}/favorite")
    assert favorite.status_code == 200
    assert favorite.json()["is_favorite"] is True

    created = client.post(
        "/api/v1/work-orders",
        json={
            "contractor_id": contractor["id"],
            "title": "Установить светильник",
            "description": "Нужен монтаж в гостиной",
            "property_id": prop["id"],
            "room_id": room["id"],
            "budget_byn": 300,
            "shared_fields": ["room_dimensions", "room_materials"],
            "consent_granted": True,
        },
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]

    dashboard = client.get(
        "/api/v1/contractor/work-orders",
        headers={"X-Contractor-Id": str(contractor["id"])},
    )
    assert dashboard.status_code == 200
    contractor_order = next(row for row in dashboard.json() if row["id"] == order_id)
    assert contractor_order["property_id"] is None
    assert contractor_order["shared_context"]["room_dimensions"]["width_m"] == 4.2
    assert "address" not in contractor_order["shared_context"]

    accepted = client.patch(
        f"/api/v1/work-orders/{order_id}/status",
        json={"status": "accepted"},
        headers={"X-Contractor-Id": str(contractor["id"])},
    )
    assert accepted.status_code == 200, accepted.text

    proposal = client.post(
        f"/api/v1/work-orders/{order_id}/proposal",
        json={"items": [{"product_id": seeded_products[0].id, "quantity": 2}]},
        headers={"X-Contractor-Id": str(contractor["id"])},
    )
    assert proposal.status_code == 200, proposal.text
    assert proposal.json()["items"][0]["unit_price_byn"] == "100.00"

    cart = client.post(f"/api/v1/work-orders/{order_id}/proposal/accept")
    assert cart.status_code == 200, cart.text
    assert cart.json()["cart"]["items"][0]["quantity"] == 2

    in_progress = client.patch(
        f"/api/v1/work-orders/{order_id}/status",
        json={"status": "in_progress"},
        headers={"X-Contractor-Id": str(contractor["id"])},
    )
    assert in_progress.status_code == 200, in_progress.text
    completed = client.patch(
        f"/api/v1/work-orders/{order_id}/status",
        json={"status": "completed"},
        headers={"X-Contractor-Id": str(contractor["id"])},
    )
    assert completed.status_code == 200, completed.text

    equipment = client.get(f"/api/v1/properties/{prop['id']}/equipment")
    assert equipment.status_code == 200
    installed = [row for row in equipment.json() if row["work_order_id"] == order_id]
    assert len(installed) == 1
    assert installed[0]["quantity"] == 2
    history = client.get(f"/api/v1/properties/{prop['id']}/history")
    assert any(row["event_type"] == "work_completed" for row in history.json())


def test_work_order_requires_explicit_consent(client):
    contractor = client.get("/api/v1/contractors").json()[0]
    response = client.post(
        "/api/v1/work-orders",
        json={
            "contractor_id": contractor["id"],
            "title": "Задача",
            "description": "Описание",
            "shared_fields": [],
            "consent_granted": False,
        },
    )
    assert response.status_code == 400


def test_project_journey_sequence_and_demo_rewards(client):
    templates = client.get("/api/v1/journeys/templates")
    assert templates.status_code == 200
    assert len(templates.json()) == 5
    template = templates.json()[0]
    created = client.post("/api/v1/journeys", json={"template_id": template["id"]})
    assert created.status_code == 201, created.text
    journey = created.json()
    steps = journey["steps"]

    too_early = client.post(
        f"/api/v1/journeys/{journey['id']}/steps/{steps[1]['id']}/complete"
    )
    assert too_early.status_code == 409

    first = client.post(
        f"/api/v1/journeys/{journey['id']}/steps/{steps[0]['id']}/complete"
    )
    assert first.status_code == 200, first.text
    balance = first.json()["loyalty_balance"]
    again = client.post(
        f"/api/v1/journeys/{journey['id']}/steps/{steps[0]['id']}/complete"
    )
    assert again.status_code == 200
    assert again.json()["loyalty_balance"] == balance

    for step in steps[1:]:
        finished = client.post(
            f"/api/v1/journeys/{journey['id']}/steps/{step['id']}/complete"
        )
        assert finished.status_code == 200, finished.text
    assert finished.json()["journey"]["status"] == "completed"
    assert finished.json()["journey"]["progress_percent"] == 100
    assert finished.json()["reward_is_demo"] is True
