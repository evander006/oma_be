# OMA. Дом — Backend

FastAPI backend for the OMA Dom renovation / home-improvement platform: local OMA.by product catalog, rooms and photos, AI room analysis and catalog-grounded recommendations, design sessions, renovation projects/estimates, cart/orders, and a **development** loyalty engine.

Flutter UI is out of scope for this repository’s backend work.

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

# Schema: create_all on startup (Alembic optional)
alembic upgrade head

# Parse sample products from oma.by (public pages; rate-limited)
python scripts/import_products.py --max-products 20

# Generate procedural GLB placeholders (real GLBs will replace these later)
python scripts/generate_3d_assets.py

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## Environment

See `.env.example`. Important:

| Variable | Purpose |
|----------|---------|
| `AI_PROVIDER` | `openrouter` (default), `nvidia`, `gemini`, or `mock` |
| `OPENROUTER_API_KEY` | OpenRouter key (NVIDIA VL routed through OpenRouter) |
| `OPENROUTER_MODEL` | Default `nvidia/nemotron-3.5-super-vl:free` |
| `NVIDIA_API_KEY` | Optional direct NVIDIA API Catalog / NIM |
| `IMAGE_GEN_PROVIDER` | `none` (default), `mock` (tests only) |
| `LOYALTY_*` | Explicitly labeled **development** loyalty rules |

Authentication is disabled for the MVP; demo user **Анна** (`GET /api/v1/me`).

**Privacy:** with `openrouter` / `nvidia` / `gemini`, room photos leave this server and are processed under the provider’s policies. Do not log image bytes or API keys.

## AI capabilities

Configured as **separate** interfaces (`GET /api/v1/ai/capabilities`):

1. **Vision-language** — room photo analysis (image **input**, JSON/text **output**). Uses OpenRouter NVIDIA VL by default.
2. **Text reasoning** — catalog ranking explanations (same chat/VL client; IDs validated in Python).
3. **Image generation/editing** — **not** provided by the free VL chat model. Default `IMAGE_GEN_PROVIDER=none` returns status `unavailable`, preserves design product selections, and allows retry. Do not treat text-only prompts as proof of product placement.

Product reference images are loaded for a future edit endpoint; the current default does **not** claim a successful product-conditioned visualization.

## Catalog

- Local `data/products/products.json` + SQLite (currently **~20** sample products in-repo; parser/import path preserved for a larger dump when provided).
- Filters: category, budget/price, color, material, style tags, room type, dimensions (unknown dimensions are never treated as a fit), installation flag.
- 3D room editor: a realistic cutaway room shell with procedural wood/tile/plaster PBR textures, soft shadows and detailed category-based furniture models.
- The scene catalog uses the existing paginated/searchable `GET /products` API. Available items can be placed in a saved design draft, dragged, rotated and removed; text search queries the backend rather than only the first visible page.
- Unpurchased design previews are stored separately in `room_design_placements` and are never reported as purchases. The existing owned layer still shows only eligible order items explicitly linked to a room.
- Procedural furniture is a visual approximation, not a manufacturer-accurate digital twin. Exact GLB files can be supplied under `data/models/products/{product_id}.glb` and are used only when marked `manufacturer_exact`.

## Renovation & loyalty

- Projects, standalone repair requests, preliminary estimates (product subtotals from catalog; labor only when a configured rule exists — demo rates are **unverified**).
- Status workflow does **not** invent contractor bookings.
- Loyalty: balance, earn/redeem, idempotent transactions, demo rewards. Rules are development-only.

## Storage

| Content | Location |
|---------|----------|
| Product images | `data/images/products/{id}/` |
| 3D models | `data/models/products/{id}.glb` |
| Room photos | `data/uploads/rooms/{room_id}/` |
| Visualizations | `data/uploads/visualizations/{session_id}/` |

API responses use relative asset URLs under `/api/v1/assets/...`, never absolute server paths.

## Tests

```bash
cd backend
pytest -q
```

Unit tests use `AI_PROVIDER=mock` and do not need live credentials.

Optional live check (manual): set `OPENROUTER_API_KEY` and call `POST /api/v1/ai/analyze-room` with a real room photo.

## API map (v1)

- `GET /health`
- Catalog: `/products`, `/products/{id}`, `/categories`
- Properties/rooms/photos; 3D scene: `/properties/{property_id}/scene`, `/scene/view/{property_id}`.
- Room placement actions: `/rooms/{room_id}/placements` and `/rooms/{room_id}/design-placements` (POST/PATCH/DELETE; ownership is kept separate from design previews).
- AI: `/ai/chat`, `/ai/analyze-room`, `/ai/recommendations`, `/ai/design-sessions`, `.../generate`, `/ai/capabilities`
- Renovation: `/renovation/projects`, `/renovation/requests`, `/renovation/estimates`, `/renovation/services`
- Loyalty: `/loyalty/account`, `/loyalty/transactions`, `/loyalty/rewards`
- Commerce: favorites, cart, orders

## Known limitations

- Catalog size in this repo is ~20 products, not 4000+ (import pipeline ready).
- Image editing with OMA product references is **not** confirmed against a live NVIDIA image-edit endpoint; generation status is honest (`unavailable` / `pending` / `failed`).
- Loyalty and renovation labor prices are **demo / development** configuration.
- Real GLB catalog assets are pending user delivery.
- Scheduling is never auto-confirmed.
