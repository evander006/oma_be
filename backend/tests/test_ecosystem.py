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
            "category": "Освещение",
            "brand": "Тестовый бренд",
            "model": "L-10",
            "serial_number": "SN-001",
            "specifications": {"мощность": "10 Вт"},
            "warranty_until": "2028-10-27T00:00:00Z",
        },
    )
    assert added.status_code == 201, added.text
    assert added.json()["product_snapshot"]["id"] == seeded_products[0].id
    assert added.json()["category"] == "Освещение"
    assert added.json()["brand"] == "Тестовый бренд"
    assert added.json()["model"] == "L-10"
    assert added.json()["serial_number"] == "SN-001"
    assert added.json()["room_name"] == "Гостиная"
    assert added.json()["source"] == "catalog"
    assert added.json()["warranty_until"].startswith("2028-10-27")

    equipment = client.get(
        f"/api/v1/properties/{prop['id']}/equipment", params={"room_id": room["id"]}
    )
    assert equipment.status_code == 200
    assert len(equipment.json()) == 1
    assert equipment.json()[0]["serial_number"] == "SN-001"
    history = client.get(f"/api/v1/properties/{prop['id']}/history")
    assert history.status_code == 200
    assert history.json()[0]["event_type"] == "equipment_added"
    assert history.json()[0]["room_name"] == "Гостиная"
    assert history.json()[0]["product_ids"] == [seeded_products[0].id]


def test_required_passport_names_cannot_be_cleared(client):
    prop, room = _home(client)
    property_response = client.patch(
        f"/api/v1/properties/{prop['id']}", json={"name": None}
    )
    room_response = client.patch(f"/api/v1/rooms/{room['id']}", json={"name": None})

    assert property_response.status_code == 422
    assert room_response.status_code == 422


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
    assert contractor_order["shared_context"]["room_dimensions"]["length_m"] == 5.1
    assert contractor_order["shared_context"]["room_dimensions"]["height_m"] is None
    assert isinstance(contractor_order["shared_context"]["room_dimensions"]["width_m"], float)
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


def test_contractor_filter_handles_cyrillic_case_and_codes(client):
    # SQLite's LIKE/LOWER are ASCII-only by default, so filtering a Cyrillic
    # title must use Unicode case-folding rather than SQL ILIKE.
    lowercase = client.get("/api/v1/contractors", params={"specialty": "элект"})
    uppercase = client.get("/api/v1/contractors", params={"specialty": "ЭЛЕКТ"})
    code = client.get("/api/v1/contractors", params={"specialty": "ELECTR"})
    unknown = client.get("/api/v1/contractors", params={"specialty": "неизвестно"})

    assert lowercase.status_code == 200
    assert uppercase.status_code == 200
    assert code.status_code == 200
    assert unknown.status_code == 200
    ids = [row["id"] for row in lowercase.json()]
    assert ids
    assert [row["id"] for row in uppercase.json()] == ids
    assert [row["id"] for row in code.json()] == ids
    assert unknown.json() == []


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


def test_contractor_scope_and_unaccepted_materials_are_not_installed(
    client, seeded_products
):
    prop, room = _home(client)
    contractors = client.get("/api/v1/contractors").json()
    assigned, other = contractors[:2]
    created = client.post(
        "/api/v1/work-orders",
        json={
            "contractor_id": assigned["id"],
            "title": "Проверить материалы",
            "description": "Предложение требует решения клиента",
            "property_id": prop["id"],
            "room_id": room["id"],
            "shared_fields": [],
            "consent_granted": True,
        },
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]

    wrong_contractor = client.patch(
        f"/api/v1/work-orders/{order_id}/status",
        json={"status": "accepted"},
        headers={"X-Contractor-Id": str(other["id"])},
    )
    assert wrong_contractor.status_code == 403

    headers = {"X-Contractor-Id": str(assigned["id"])}
    assert client.patch(
        f"/api/v1/work-orders/{order_id}/status",
        json={"status": "accepted"},
        headers=headers,
    ).status_code == 200
    proposal = client.post(
        f"/api/v1/work-orders/{order_id}/proposal",
        json={"items": [{"product_id": seeded_products[0].id, "quantity": 1}]},
        headers=headers,
    )
    assert proposal.status_code == 200, proposal.text
    assert client.patch(
        f"/api/v1/work-orders/{order_id}/status",
        json={"status": "in_progress"},
        headers=headers,
    ).status_code == 200
    assert client.patch(
        f"/api/v1/work-orders/{order_id}/status",
        json={"status": "completed"},
        headers=headers,
    ).status_code == 200

    equipment = client.get(f"/api/v1/properties/{prop['id']}/equipment").json()
    assert not any(item["work_order_id"] == order_id for item in equipment)


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
