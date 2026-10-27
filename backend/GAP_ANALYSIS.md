# Gap analysis — OMA. Дом renovation platform (2026-10-27)

## Existing (keep)

| Area | Status |
|------|--------|
| FastAPI `/api/v1` | Working: products, rooms, cart, favorites, orders, AI chat/recommendations |
| Auth | MVP demo user **Анна** (no JWT required) |
| Catalog | SQLite + `products.json` import pipeline + OMA.by parser |
| AI | OpenRouter OpenAI-compatible client; default vision model `nvidia/nemotron-3.5-super-vl:free` |
| Assets | Local product images, procedural GLBs for current sample, room photo upload |
| Tests | 13 unit tests (mock AI) |

## Status after renovation platform work

| Requirement | Status |
|-------------|--------|
| 4,000+ products | **Still ~20 in-repo.** Parser/import preserved; larger dump when provided. |
| NVIDIA | OpenRouter VL default; optional `AI_PROVIDER=nvidia` → `integrate.api.nvidia.com`. |
| Capability split | `ai_capabilities.py`: vision / reasoning / image-gen. |
| RoomAnalysis | Persisted + `POST /ai/analyze-room`. |
| Design sessions | Versions, selected products, viz status, generate + retry. |
| Image editing | Pluggable; default `unavailable` (honest). Mock provider for tests only. |
| Renovation / estimates | Projects, requests, estimates, services seed. |
| Loyalty | Account, txs, rewards; development rules; idempotency. |
| Catalog filters | color, material, style, room_type, dims, installation. |
| 3D | Sample/procedural GLBs; real assets pending. |
