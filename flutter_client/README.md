# Flutter integration notes (OMA. Дом)

This backend repository (`oma_be`) does **not** contain the Flutter application sources.
Use the Dart client stubs below in the existing OMA Dom Flutter app.

## Base URL configuration

Do not hardcode `localhost` for all devices:

| Target | Example base URL |
|--------|------------------|
| Android emulator | `http://10.0.2.2:8000` |
| iOS simulator | `http://127.0.0.1:8000` |
| Physical device | `http://<LAN-IP-of-dev-machine>:8000` |

Provide these via `--dart-define=API_BASE_URL=...` or a flavor config.

## Suggested wiring

1. Keep existing repository interfaces (mock + remote).
2. Point the remote implementation at `/api/v1/*` using `lib/oma_api_client.dart`.
3. Map `ProductOut` JSON to your existing product models.
4. For 3D, load GLB from `product.model_3d.url` (relative to API base). Use a package such as `model_viewer_plus` / `flutter_gl` only if platform support is confirmed; otherwise show a placeholder that is **not** presented as an interactive 3D scene when `has_3d_model` is false.
5. AI chat: `POST /api/v1/ai/chat` and `POST /api/v1/ai/recommendations/from-room`.
6. Never embed Gemini keys in the Flutter app.

## Auth

None for MVP. Backend always uses demo user **Анна** (`GET /api/v1/me`). No tokens.
