# OMA. Дом Backend (`oma_be`)

Python FastAPI backend for **OMA. Дом**: OMA.by product parser, local catalog + images, procedural GLB assets, REST API, and multimodal AI assistant.

The Flutter mobile app is **not** in this repository. A Dart client stub lives in `flutter_client/`.

See [backend/README.md](backend/README.md) for install, import, and run instructions.

## MVP deployment

The API is ready for Vercel deployment from the repository root. `main.py` exports the
FastAPI application, while `vercel.json` routes all requests to the Python function.
On Vercel, the bundled demo catalog seeds a temporary SQLite database in `/tmp` so the
MVP starts without external infrastructure.

This SQLite database is intentionally ephemeral. Before importing the completed OMA
catalog, configure a persistent PostgreSQL `DATABASE_URL`, run the migrations, and use
the catalog import described in [backend/README.md](backend/README.md). The mobile
frontend is deployed separately and is not modified by this setup.

Useful checks after deployment:

- `/api/v1/health` — API health;
- `/docs` — interactive OpenAPI documentation;
- `/api/v1/products?page=1&page_size=20` — seeded MVP catalog.
