# OMA. Дом — Backend state (for Claude)

**As of:** 2026-10-27  
**Repo:** `oma_be` — FastAPI backend for OMA.by renovation / interior / shopping platform.  
**Flutter UI:** out of scope here (`flutter_client/` is a thin Dart stub only).  
**Live deploy:** Render Docker free tier — see `RENDER.md`, `render.yaml`. Example host: `https://oma-be-85l2.onrender.com`.

Use this file as the single source of truth for what exists now. Older docs (`IMPLEMENTATION_REPORT.md`, `GAP_ANALYSIS.md`) may be stale on catalog size / AI defaults.

---

## 1. Product purpose

Unified backend for:

1. Turnkey renovation requests + individual repair/installation services  
2. AI interior help from room photos + **real OMA catalog products**  
3. Design sessions / versions / visualization status (honest if image-edit unavailable)  
4. Catalog browse, cart, demo orders  
5. Development loyalty program (explicitly **not** official OMA rules)

Demo identity: user **Анна** (`anna@oma.local`). Auth/JWT disabled for MVP — every request resolves to Анна via `get_current_user`.

---

## 2. Stack & layout

| Layer | Choice |
|-------|--------|
| Language | Python 3.13 |
| API | FastAPI, OpenAPI at `/docs` |
| Prefix | `/api/v1` |
| ORM | SQLAlchemy 2 |
| DB | SQLite default (`backend/data/oma_dom.db`); `create_all` + SQLite column patches on startup |
| Migrations | Alembic present (`0001_initial`); startup also creates/patches schema |
| HTTP client | httpx (`trust_env=False` for OMA parser — system proxy breaks HosterGuard) |
| Images | Pillow |
| Tests | pytest + TestClient + mock AI |

```
oma_be/
  backend/
    app/
      main.py                 # FastAPI + lifespan seed
      api/deps.py             # demo user Анна, ownership helpers
      api/routes/             # health, profile, products, assets, rooms,
                              # commerce, ai, renovation, loyalty
      core/                   # config, logging, security (legacy)
      db/                     # base, session, models/, schema_utils
      schemas/                # Pydantic DTOs
      services/               # catalog, AI, design, estimate, loyalty, images, 3D, URLs
      integrations/oma/       # OMA.by HTML parser
    alembic/
    scripts/                  # import_products, generate_3d_assets, cleanup_*
    data/
      products/products.json  # catalog dump
      images/products/{id}/
      models/products/{id}.glb
      uploads/rooms|visualizations/
      cache/pages/            # HTML cache for parser
      oma_dom.db
    tests/
  flutter_client/             # Dart API notes/stub — not the Flutter app
  Dockerfile, docker-compose.yml, render.yaml, requirements.txt
```

---

## 3. Catalog (current numbers)

| Metric | Value |
|--------|-------|
| Products in `products.json` / SQLite | **1040** |
| Category IDs in dump | **43** |
| Local image folders | **1040** |
| Procedural GLB files | **~21** (most products have no real GLB yet) |

### Import / parser

- Script: `backend/scripts/import_products.py`
- Parser: `backend/app/integrations/oma/parser.py`
- Features: many leaf category seeds, Bitrix `PAGEN_1` pagination, **merge** with existing JSON, `--additional N`, rate limit, image download, `trust_env=False`
- Prices are **snapshots** (`price_retrieved_at`); not live cart pricing from OMA checkout
- robots.txt: use public category/product HTML only; avoid `/api/*`

```bash
cd backend
# append 920 new (example already done)
python scripts/import_products.py --additional 920 --max-pages 10 --max-images 1
# or replace/target total
python scripts/import_products.py --max-products 100 --no-merge
# JSON → DB only
python scripts/import_products.py --skip-fetch
```

### Product fields (normalized + source extras)

Stable internal `id`, source id/SKU when found, name, brand, category, description, specs, dimensions (mm), materials, colors, `style_tags`, `room_types`, installation notes/flag, image refs, price + currency + retrieval time, availability when present, `source_url`, 3D metadata (`has_3d_model`, paths, limitations).

### Catalog API filters

`GET /api/v1/products` supports: `q`, `category_id`, `min_price`/`max_price`, `color`, `material`, `style`, `room_type`, `installation_compatible`, `max_width_mm` / `max_height_mm` / `max_depth_mm`, sort, pagination.  
**Unknown dimensions stay unknown** — never treated as a fit solely by name/category.

---

## 4. Database models

### Core (`app/db/models/__init__.py`)

User, Category, Product, ProductImage, ProductSpecification, Property, Room, RoomPhoto, RoomPlacement, Favorite, Cart, CartItem, InstallationService, Order, OrderItem, ChatSession, ChatMessage

### Renovation / design / loyalty (`app/db/models/renovation.py`)

RoomAnalysis, DesignSession, DesignVersion, SelectedDesignProduct, GeneratedVisualization, RenovationService, RenovationProject, RenovationWorkItem, RenovationRequest, InstallationRequest, Estimate, EstimateLine, LoyaltyAccount, LoyaltyTransaction

Schema evolution for SQLite: `app/db/schema_utils.ensure_sqlite_product_columns` (adds `style_tags`, `room_types`, installation columns if missing).

---

## 5. AI architecture

### Providers (`AI_PROVIDER`)

| Value | Role |
|-------|------|
| `openrouter` (**default**) | OpenAI-compatible chat; model `nvidia/nemotron-3.5-super-vl:free` (+ free VL fallbacks) |
| `nvidia` | Direct `https://integrate.api.nvidia.com/v1` |
| `gemini` | Google GenAI (often overloaded on free tier) |
| `mock` | Offline / tests |

Factory: `app/services/ai_provider.py`  
Capability split: `app/services/ai_capabilities.py`

| Capability | Input | Output | Status |
|------------|-------|--------|--------|
| Vision-language | room photos + text | structured JSON analysis | **Working** via VL chat |
| Text reasoning / ranking | analysis + catalog JSON | ranked **real** product IDs + reasons | **Working**; IDs validated in Python |
| Image generation / edit | room photo + product reference images | edited visualization | **`IMAGE_GEN_PROVIDER=none` → status `unavailable`** (honest). `mock` for tests only (returns original photo, not product-conditioned). |

**Do not claim** product placement / room editing works until a real image-edit endpoint is wired and tested.  
**Privacy:** photos leave the server to the configured host; never log API keys or image bytes.

Introspection: `GET /api/v1/ai/capabilities`

### Related services

- `room_analysis_service.py` — multimodal analysis + Pydantic validation + `RoomAnalysis` persistence  
- `recommendation_service.py` — catalog-grounded chat/recommendations + budget enforcement  
- `design_service.py` — sessions, versions, selected products, generate workflow, viz asset paths  

---

## 6. Renovation & loyalty

### Estimates (`estimate_service.py`)

- Product subtotal from catalog prices (Python)  
- Labor only if `RenovationService` has a rate; demo rates are **`price_verified=False`**  
- Statuses like `preliminary` / `incomplete` / `consultation_required`  
- Disclaimer: not a confirmed contractor quote  

### Projects / requests

Statuses include draft → submitted → awaiting consultation → … → completed / cancelled.  
**Never** auto-confirm contractor booking/date (`scheduling_confirmed=false` on installation requests).

### Loyalty (`loyalty_service.py`)

- Configurable earn/redeem rates in env  
- Server-side balance; client cannot set balance  
- Idempotency keys; no negative balance unless configured  
- Labelled development program  

---

## 7. API map (`/api/v1`)

Base: local `http://127.0.0.1:8000` · Swagger `/docs` · `/` redirects to docs.

### Health / profile

| Method | Path |
|--------|------|
| GET | `/health` |
| GET | `/me` |

### Catalog

| Method | Path |
|--------|------|
| GET | `/products` |
| GET | `/products/{product_id}` |
| GET | `/products/{product_id}/images` |
| GET | `/products/{product_id}/3d` |
| GET | `/categories` |
| GET | `/categories/{category_id}/products` |

### Assets (relative URLs only — never absolute server paths)

| Method | Path |
|--------|------|
| GET | `/assets/products/{id}/images/{filename}` |
| GET | `/assets/products/{id}/model.glb` |
| GET | `/assets/rooms/{room_id}/{filename}` (owner) |
| GET | `/assets/visualizations/{session_id}/{filename}` (owner) |

### Properties / rooms

| Method | Path |
|--------|------|
| POST/GET | `/properties` |
| GET/DELETE | `/properties/{property_id}` |
| POST/GET | `/rooms` |
| GET | `/rooms/{room_id}` |
| POST/GET | `/rooms/{room_id}/photos` |
| DELETE | `/rooms/{room_id}/photos/{photo_id}` |
| GET | `/rooms/{room_id}/recommendations` |
| POST | `/rooms/{room_id}/placements` |

### Commerce

| Method | Path |
|--------|------|
| GET/POST/DELETE | `/favorites`, `/favorites/{product_id}` |
| GET | `/cart` |
| POST/DELETE | `/cart/items`, `/cart/items/{product_id}` |
| GET | `/installation-services` |
| POST/GET | `/orders` |

Orders are **demo** (`is_demonstration=true`); may accrue loyalty points with idempotency.

### AI

| Method | Path | Notes |
|--------|------|-------|
| GET | `/ai/capabilities` | provider/model + image-gen honesty |
| POST | `/ai/chat` | catalog-grounded assistant |
| POST | `/ai/recommendations` | text and/or room |
| POST | `/ai/analyze-room` | **structured** analysis (persisted) |
| POST | `/ai/recommendations/from-room` | analysis + product picks |
| POST | `/ai/design-sessions` | create |
| GET | `/ai/design-sessions/{id}` | session + versions |
| GET | `/ai/design-sessions/{id}/versions` | |
| POST | `/ai/design-sessions/{id}/analyze` | |
| POST | `/ai/design-sessions/{id}/generate` | may return `unavailable`; selections kept; retry allowed |

### Renovation

| Method | Path |
|--------|------|
| GET | `/renovation/services` |
| POST/GET | `/renovation/projects` |
| GET/PATCH/DELETE | `/renovation/projects/{id}` |
| POST/GET | `/renovation/requests`, `/renovation/requests/{id}` |
| POST/GET | `/renovation/estimates`, `/renovation/estimates/{id}` |
| POST | `/renovation/installation-requests` |

### Loyalty

| Method | Path |
|--------|------|
| GET | `/loyalty/account` |
| GET | `/loyalty/transactions` |
| GET | `/loyalty/rewards` |
| POST | `/loyalty/earn` |
| POST | `/loyalty/redeem` |

---

## 8. Storage & privacy

| Content | Path |
|---------|------|
| Product images | `data/images/products/{id}/` |
| 3D GLB | `data/models/products/{id}.glb` |
| Room photos | `data/uploads/rooms/{room_id}/` |
| Visualizations | `data/uploads/visualizations/{session_id}/` |
| Parser HTML cache | `data/cache/pages/` |

- Validate MIME/size on upload; re-encode; ownership checks on private assets  
- Delete supported for properties / room photos / renovation projects  
- Secrets only in env; `.env.example` has placeholders only  

---

## 9. Environment (key vars)

See `backend/.env.example`.

| Group | Vars |
|-------|------|
| App/DB | `DATABASE_URL`, `CORS_ORIGINS`, `ENVIRONMENT`, `DEBUG` |
| AI | `AI_PROVIDER`, `OPENROUTER_*`, `NVIDIA_*`, `GEMINI_*` |
| Image gen | `IMAGE_GEN_PROVIDER`, `IMAGE_GEN_MODEL`, `IMAGE_GEN_MAX_PRODUCT_REFS` |
| Loyalty | `LOYALTY_EARN_RATE_PER_BYN`, `LOYALTY_REDEEM_VALUE_PER_POINT`, `LOYALTY_ALLOW_NEGATIVE`, `LOYALTY_PROGRAM_LABEL` |
| Parser | `OMA_MAX_PRODUCTS`, `OMA_REQUEST_DELAY_SECONDS`, `OMA_ALLOW_INSECURE_SSL` |
| Uploads | `MAX_UPLOAD_BYTES`, `MAX_ROOM_PHOTOS`, `RATE_LIMIT_AI_PER_MINUTE` |

Render: set `OPENROUTER_API_KEY` in dashboard; free disk is ephemeral — catalog re-seeds from baked `products.json` if DB empty.

---

## 10. Run / test / deploy

```bash
# local
cd backend
# activate venv from repo root: ..\.venv\Scripts\activate
pip install -r ../requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# tests (no live AI keys)
pytest -q
# last known: 26 passed (api + renovation platform + parser fixtures)
```

Flutter connect:

- Android emulator → `http://10.0.2.2:8000`  
- iOS sim → `http://127.0.0.1:8000`  
- Device → LAN IP or Render URL  

---

## 11. Important services (code map)

| File | Responsibility |
|------|----------------|
| `services/catalog_service.py` | JSON upsert, list/filter, AI candidate filter |
| `services/ai_provider.py` | Mock / OpenRouter / NVIDIA / Gemini client |
| `services/ai_capabilities.py` | Vision / reasoning / image-gen interfaces |
| `services/room_analysis_service.py` | Structured room analysis |
| `services/recommendation_service.py` | Chat + recommendations |
| `services/design_service.py` | Design sessions & visualization workflow |
| `services/estimate_service.py` | Preliminary estimates |
| `services/loyalty_service.py` | Points earn/redeem/idempotency |
| `services/image_service.py` | Upload validation/resize |
| `services/model3d_service.py` | Procedural GLB helpers |
| `services/asset_urls.py` | Public relative URLs + product serialization |
| `integrations/oma/parser.py` | OMA.by scrape/import |

---

## 12. Hard constraints / honesty rules (do not violate)

1. Never invent products, prices, SKUs, URLs, or availability — only DB/catalog.  
2. Never invent official OMA loyalty or contractor prices.  
3. Never claim image generation succeeded when status is `unavailable`/`failed`.  
4. Never claim scheduling/booking confirmed without a real scheduler.  
5. Never expose API keys or absolute filesystem paths in API responses/logs.  
6. Do not replace NVIDIA/OpenRouter with another provider without proving a capability gap.  
7. Do not full re-crawl unnecessarily — merge/import from `products.json` when possible.  
8. Real GLBs: user will supply later; keep product IDs stable; place files at `data/models/products/{id}.glb`.  
9. Auth is intentionally off — do not “fix” by adding JWT unless asked.

---

## 13. Known limitations & next steps

| Gap | Notes |
|-----|-------|
| Image edit with product refs | Not live; pluggable stub |
| Real 3D catalog | ~21 procedural GLBs; awaiting real assets |
| Catalog vs 4000+ | **1040** imported; parser can grow further |
| Auth | Demo Анна only |
| Orders/payments | Demonstration only |
| Labor rates | Unverified development seeds |
| Free Render disk | Ephemeral; rely on JSON seed + env keys |
| AI rate limit | In-memory per process |

**Suggested next (when asked):** wire real image-edit NIM; drop GLBs; grow catalog; official loyalty/pricing rules; re-enable auth for production.

---

## 14. One-line summary for Claude

Working FastAPI renovation backend: **1040 OMA products**, OpenRouter **NVIDIA VL** for room analysis + catalog-grounded recommendations, design sessions with **honest unavailable** image gen, renovation/estimate/loyalty APIs, demo user Анна, SQLite + local assets, tests with mock AI — Flutter is separate.
