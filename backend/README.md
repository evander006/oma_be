# OMA. Дом — Backend

FastAPI backend for the OMA Dom Flutter MVP: local OMA.by product catalog, assets, 3D GLB approximations, rooms/cart/favorites/orders, and a multimodal AI assistant (Gemini or mock).

## Quick start

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -r ../requirements.txt
copy .env.example .env   # or cp .env.example .env

# DB schema (create_all on startup also works; Alembic optional)
alembic upgrade head

# Parse 20 products from oma.by (public pages; rate-limited)
python scripts/import_products.py --max-products 20

# Generate procedural GLB approximations
python scripts/generate_3d_assets.py

# Run API
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## Tests

```bash
cd backend
pytest -q
```

Unit tests use fixtures + mock AI and do not need network or Gemini keys.

## Environment

See `.env.example`. Important:

- `AI_PROVIDER=mock` for offline demo / CI
- `AI_PROVIDER=gemini` + `GEMINI_API_KEY` for real vision+text
- Default model: `gemini-3.8-flash` (free-tier multimodal). Override with `GEMINI_MODEL` if needed.
- Authentication is disabled for the MVP. All requests use shared demo user **Анна** (`GET /api/v1/me`).

**Privacy:** when using Gemini, uploaded room photos are sent to Google for analysis. They are not processed exclusively on-device.

## Docker

From repo root:

```bash
docker compose up --build
```

## Manual import fallback

If automated retrieval is blocked, place a JSON array at `data/products/products.json` (same schema as parser output), put images under `data/images/products/{product_id}/`, then:

```bash
python scripts/import_products.py --skip-fetch
```

## robots.txt note

OMA.by disallows `/api/*`, search, personal pages, etc. Category and product HTML pages used by this parser are not disallowed. The crawler uses a clear User-Agent, delays, caching, and only public fields.
