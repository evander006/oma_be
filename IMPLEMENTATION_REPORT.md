# OMA. Дом Backend — Implementation Report

Date: 2026-10-26

## Context / repository findings

- Workspace `oma_be` was essentially empty (`main.py` + `.idea`).
- No Flutter app, no `OMA_Dom_Flutter_Cursor_Spec.md`, and no existing Python backend were present in this repository.
- Implementation therefore focuses on a complete local backend + dataset + Dart client stub for integration into the separate Flutter project.

## Backend architecture

```
oma_be/
  backend/
    app/
      main.py                 # FastAPI app
      api/deps.py + routes/   # REST /api/v1
      core/                   # config, logging, security
      db/                     # SQLAlchemy models, session
      schemas/                # Pydantic DTOs
      services/               # catalog, AI, images, 3D, URLs
      integrations/oma/       # OMA.by parser
      integrations/gemini/    # provider package
    alembic/                  # migrations
    scripts/                  # import + GLB generation
    data/
      products/products.json
      images/products/{id}/
      models/products/{id}.glb
      oma_dom.db
    tests/
  flutter_client/             # Dart API stub + notes
  requirements.txt
  Dockerfile
  docker-compose.yml
```

Stack: Python 3.13 (venv), FastAPI, SQLAlchemy 2, Alembic, SQLite, httpx, BeautifulSoup, Pillow, pygltflib, google-genai (optional), pytest.

## Commands

```bash
# 1) deps
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2) env
copy backend\.env.example backend\.env

# 3) migrations (optional; create_all also runs on startup)
cd backend
set PYTHONPATH=%CD%
alembic upgrade head

# 4-7) parse + import + images (images saved during parse)
python scripts\import_products.py --max-products 20

# 8) GLB assets
python scripts\generate_3d_assets.py

# 9) start API
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# Swagger: http://127.0.0.1:8000/docs

# 10) tests
python -m pytest -q

# 11) Flutter
# Point the existing app at:
#   Android emulator: http://10.0.2.2:8000
#   iOS simulator:    http://127.0.0.1:8000
#   Device:           http://<LAN-IP>:8000
# Use flutter_client/lib/oma_api_client.dart as a starting point.
```

Docker: `docker compose up --build` from repo root.

## Database

- Default: SQLite at `backend/data/oma_dom.db`
- Models: User, Category, Product, ProductImage, ProductSpecification, Property, Room, RoomPhoto, RoomPlacement, Favorite, Cart, CartItem, InstallationService, Order, OrderItem, ChatSession, ChatMessage
- Alembic revision `0001_initial` creates schema via metadata
- Path to PostgreSQL: set `DATABASE_URL=postgresql+psycopg://...`

## Parser results

| Metric | Value |
|--------|-------|
| Products discovered (category links scanned) | 121 |
| Parsed / validated / imported | 20 / 20 / 20 |
| Failed | 0 |
| Local image files retained | 20 (1 primary per product after cleanup) |
| GLB files generated + validated | 20 / 20 |
| Categories covered | lighting, lighting-ceiling, furniture, plumbing-faucets, plumbing-sinks |

Source: public OMA.by HTML + JSON-LD. Prices stored with `price_retrieved_at` and must be treated as snapshot values.

robots.txt: product/category pages used are not disallowed; `/api/*`, search, personal areas are avoided.

Manual fallback: edit `backend/data/products/products.json` + local images, then `python scripts/import_products.py --skip-fetch`.

## AI

- Interface: `AIProvider` with `MockAIProvider` and `GeminiAIProvider`
- Default: `AI_PROVIDER=mock`
- Configured model ID: **`gemini-3.8-flash`** (free-tier multimodal text+image per current Google pricing docs)
- Set `AI_PROVIDER=gemini` and `GEMINI_API_KEY=...` for live vision chat
- Recommendations are catalog-grounded; product IDs are validated against DB; budget totals enforced server-side
- Privacy: with Gemini, room photos are sent to Google — documented in README / `.env.example`

## API summary (`/api/v1`)

- `GET /health`
- Auth: `POST /auth/register|login|demo`, `GET /auth/me`
- Catalog: `GET /products`, `/products/{id}`, `/products/{id}/images`, `/products/{id}/3d`, `/categories`, `/categories/{id}/products`
- Assets: `/assets/products/...`, `/assets/rooms/...` (room photos require ownership)
- Rooms/properties + photo upload
- Favorites, cart, installation services, demo orders
- AI: `POST /ai/chat`, `/ai/recommendations`, `/ai/analyze-room`, `/ai/recommendations/from-room`
- `GET /rooms/{id}/recommendations`

## 3D models

- Format: GLB (procedural geometry via pygltflib/numpy)
- Source website did not provide downloadable product GLBs for these items
- Status field: `procedural_python` / `ready`
- Explicit limitation text: approximation only, not a photogrammetric twin
- Blender not required (and was not installed)

## Tests

```
13 passed
```

Coverage includes parser fixture, duplicate upsert, listing/search/filters, uploads, ownership, mock AI, budget totals, GLB validation, cart/favorites/orders.

## Flutter integration status

- Flutter sources are **not in this repo** → full in-app wiring could not be completed here
- Delivered: `flutter_client/` Dart client + base-URL guidance
- Next step in the Flutter repo: replace mock repositories with `OmaApiClient`, keep mock backend for offline

## Environment variables

See `backend/.env.example`. Critical: `SECRET_KEY`, `AI_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `DEV_MODE`, `DATABASE_URL`.

No real secrets committed (`.env` gitignored).

## Known limitations / next steps

1. Flutter app lives elsewhere — integrate the Dart client into that project.
2. Spec/Figma file was not available in-repo — UI was not modified.
3. Category mix favors lighting/furniture/plumbing; kitchen/bath/mirrors seeds exist and can be used by raising `--max-products` or adjusting seed weights.
4. Some products lack source dimensions → GLB uses labeled approximate proportions.
5. Live Gemini not exercised in CI (no API key in environment); mock provider used for tests.
6. passlib/bcrypt version warning on Python 3.13 — functional for demo; consider migrating password hashing to raw bcrypt if needed.
7. Request rate limiting for AI is in-memory (single-process).

## Smoke verification

- Backend starts; `/api/v1/health` → ok
- `/docs` → 200
- `/api/v1/products` returns 20 catalog items with image + 3D URLs
