"""Real image metadata must point to the actual successfully downloaded URL."""
from io import BytesIO
from pathlib import Path
import json
import sys

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_full_visual_index import fetch_product_image, _prefetched_images


def test_alternative_photo_url_is_preserved():
    stream = BytesIO()
    Image.new("RGB", (32, 32), "red").save(stream, format="JPEG")
    image_bytes = stream.getvalue()
    first = "https://example.org/broken.jpg"
    second = "https://example.org/valid.jpg"
    seen = []

    def serve(request):
        seen.append(str(request.url))
        if str(request.url) == first:
            return httpx.Response(404)
        return httpx.Response(200, content=image_bytes)

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        result = fetch_product_image(client, json.dumps([first, second]), request_delay=0)
    assert result is not None
    bitmap, selected_url = result
    assert selected_url == second
    assert bitmap.size == (32, 32)
    assert seen == [first, second]
    bitmap.close()


def test_unrecognized_protocol_never_downloaded():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        assert fetch_product_image(client, '["file:///tmp/secret","http://localhost/admin"]', request_delay=0) is None


def test_skips_1x1_placeholder_and_tries_next_photo():
    """Regression for Windows user crash: SigLIP2 cannot infer tiny RGB layouts."""
    placeholder = BytesIO()
    valid = BytesIO()
    Image.new("RGB", (1, 1), "red").save(placeholder, format="PNG")
    Image.new("RGB", (64, 64), "green").save(valid, format="PNG")
    first = "https://example.org/tiny.png"
    second = "https://example.org/real.png"
    seen = []

    def serve(request):
        seen.append(str(request.url))
        return httpx.Response(
            200, content=placeholder.getvalue() if str(request.url) == first else valid.getvalue()
        )

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        result = fetch_product_image(client, json.dumps([first, second]), request_delay=0)

    assert result is not None
    picture, selected_url = result
    assert selected_url == second
    assert picture.size == (64, 64)
    assert seen == [first, second]
    picture.close()


def test_skips_all_tiny_placeholders_without_crash():
    placeholder = BytesIO()
    Image.new("RGB", (1, 1), "white").save(placeholder, format="PNG")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=placeholder.getvalue())
        )
    ) as client:
        assert fetch_product_image(
            client, '["https://example.org/tiny.png"]', request_delay=0
        ) is None



def test_parallel_prefetch_preserves_row_order_and_real_downloads():
    image = BytesIO()
    Image.new("RGB", (48, 48), "blue").save(image, format="JPEG")
    seen = []

    def respond(request):
        seen.append(str(request.url))
        return httpx.Response(200, content=image.getvalue())

    rows = [
        (i, ("sku-%d" % i, "name", "category", "brand",
             json.dumps([f"https://example.org/{i}.jpg"]), None))
        for i in range(7)
    ]
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        actual = list(_prefetched_images(client, iter(rows), workers=3, request_delay=0))
    try:
        assert [r[0] for r, _ in actual] == list(range(7))
        assert all(photo is not None and photo[0].size == (48, 48) for _, photo in actual)
        assert len(seen) == 7
    finally:
        for _, photo in actual:
            if photo is not None:
                photo[0].close()


def test_prefetch_single_worker_respects_existing_behavior():
    image = BytesIO()
    Image.new("RGB", (48, 48), "blue").save(image, format="PNG")
    rows = [(1, ("sku", "name", "cat", "brand",
                 '["https://example.org/photo.png"]', None))]
    with httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=image.getvalue())
    )) as client:
        output = list(_prefetched_images(client, rows, workers=1, request_delay=0))
    assert output[0][0][0] == 1
    assert output[0][1][1] == "https://example.org/photo.png"
    output[0][1][0].close()
