"""Regression: PDF endpoints yield real binary documents, Cyrillic font."""
from __future__ import annotations


def test_home_and_equipment_pdf_downloads(client, seeded_products):
    prop = client.post("/api/v1/properties", json={
        "name":"Квартира для паспорта", "property_type":"apartment",
    })
    assert prop.status_code == 200
    prop_id = prop.json()["id"]
    room = client.post("/api/v1/rooms", json={
        "property_id":prop_id, "name":"Кухня",
        "room_type":"kitchen", "width_m":3.2,
    })
    assert room.status_code == 200
    added = client.post(f"/api/v1/properties/{prop_id}/equipment", json={
        "room_id":room.json()["id"],
        "name":"Смеситель",
        "specifications":{"материал":"латунь"},
    })
    assert added.status_code == 201, added.text
    home = client.get(f"/api/v1/properties/{prop_id}/passport.pdf")
    assert home.status_code == 200, home.text[:200] if home.status_code != 200 else ""
    assert home.headers["content-type"].startswith("application/pdf")
    assert home.content.startswith(b"%PDF-")
    assert len(home.content) > 1000
    item = client.get(
        f"/api/v1/properties/{prop_id}/equipment/{added.json()['id']}/passport.pdf"
    )
    assert item.status_code == 200, item.text[:200] if item.status_code != 200 else ""
    assert item.content.startswith(b"%PDF-")
    assert len(item.content) > 1000
    assert client.get("/api/v1/properties/999999/passport.pdf").status_code == 404
    assert client.get(
        f"/api/v1/properties/{prop_id}/equipment/999999/passport.pdf"
    ).status_code == 404
