"""Local partial-index demo HTTP interface regression checks."""
from io import BytesIO
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import serve_partial_visual_api as partial


def jpeg_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (100, 90), (100, 30, 20)).save(stream, "JPEG")
    return stream.getvalue()


def test_local_demo_api_returns_real_sku_from_partial_index(monkeypatch, tmp_path):
    monkeypatch.setattr(partial, "read_index_status", lambda root: (
        {"catalog_count": 134187, "complete": False}, 13200
    ))
    monkeypatch.setattr(partial, "search_saved_partial_index",
        lambda root, image, limit: (
            [{"sku": "1.100083", "name": "Демонстрационный товар",
              "visual_similarity": 0.89, "image_url": "https://www.oma.by/example.jpg"}],
            13200, 134187
        )
    )
    client = TestClient(partial.create_app(tmp_path))
    status = client.get("/api/v1/visual-search/status")
    assert status.status_code == 200
    assert status.json()["partial_index"] is True
    assert status.json()["indexed_products"] == 13200
    response = client.post("/api/v1/visual-search", files={
        "file": ("camera.jpg", jpeg_bytes(), "image/jpeg")
    })
    assert response.status_code == 200
    data = response.json()
    assert data["method"] == "siglip2_catalog_embeddings"
    assert data["matches"][0]["sku"] == "1.100083"
    assert data["partial_index"] is True


def test_local_api_rejects_tiny_or_bad_uploads(tmp_path):
    client = TestClient(partial.create_app(tmp_path))
    tiny = BytesIO()
    Image.new("RGB", (1, 1)).save(tiny, "JPEG")
    response = client.post("/api/v1/visual-search", files={
        "file": ("camera.jpg", tiny.getvalue(), "image/jpeg")
    })
    assert response.status_code == 400
    wrong_mime = client.post("/api/v1/visual-search", files={
        "file": ("file.txt", b"text", "text/plain")
    })
    assert wrong_mime.status_code == 415
