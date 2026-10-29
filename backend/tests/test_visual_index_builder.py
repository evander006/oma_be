"""Real image metadata must point to the actual successfully downloaded URL."""
from io import BytesIO
from pathlib import Path
import json
import sys

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_full_visual_index import fetch_product_image


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
