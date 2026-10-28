"""Visual search must use the uploaded image and catalog assets."""
from io import BytesIO

from PIL import Image

from app.api.routes.visual_search import feature_similarity, image_features


def _png(color):
    stream = BytesIO()
    Image.new("RGB", (90, 90), color).save(stream, format="PNG")
    return stream.getvalue()


def test_color_similarity_really_depends_on_pixels():
    red = image_features(_png((220, 25, 25)))
    red_variant = image_features(_png((218, 28, 28)))
    blue = image_features(_png((18, 30, 205)))
    assert feature_similarity(red, red_variant) > feature_similarity(red, blue)


def test_photo_search_returns_grounded_catalog_results(client, seeded_products, settings):
    for index, product in enumerate(seeded_products):
        folder = settings.images_dir / product.id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "00.jpg").write_bytes(_jpeg((220, 20, 20) if index == 0 else (15, 30, 220)))
    response = client.post(
        "/api/v1/visual-search",
        files={"file": ("photo.png", _png((220, 20, 20)), "image/png")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["method"] == "local_color_histogram"
    assert payload["matches"][0]["product_id"] == seeded_products[0].id
    assert payload["matches"][0]["is_exact_match"] is False
    assert all(row["product_id"] in {p.id for p in seeded_products} for row in payload["matches"])


def _jpeg(color):
    stream = BytesIO()
    Image.new("RGB", (80, 80), color).save(stream, format="JPEG")
    return stream.getvalue()


def test_invalid_upload_rejected(client):
    bad_type = client.post(
        "/api/v1/visual-search",
        files={"file": ("bad.txt", b"not an image", "text/plain")},
    )
    assert bad_type.status_code == 415
    bad_bytes = client.post(
        "/api/v1/visual-search",
        files={"file": ("bad.jpg", b"not an image", "image/jpeg")},
    )
    assert bad_bytes.status_code == 400
