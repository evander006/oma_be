# Deploy OMA Dom API on Render (free)

## 1. Push code to GitHub

Repo: `https://github.com/evander006/oma_be.git`

```bat
git add -A
git commit -m "Prepare Render deploy"
git push origin main
```

## 2. Create Web Service on Render

1. Go to [https://dashboard.render.com](https://dashboard.render.com) → **New** → **Web Service**
2. Connect GitHub repo **`oma_be`**
3. Settings:
   - **Name:** `oma-dom-api`
   - **Language / Runtime:** **Docker**
   - **Branch:** `main`
   - **Dockerfile path:** `./Dockerfile`
   - **Instance type:** **Free**
4. **Environment variables** (Environment tab):

| Key | Value |
|-----|--------|
| `ENVIRONMENT` | `production` |
| `DEBUG` | `false` |
| `CORS_ORIGINS` | `*` |
| `AI_PROVIDER` | `openrouter` |
| `OPENROUTER_API_KEY` | *(key from https://openrouter.ai/keys)* |
| `OPENROUTER_MODEL` | `nvidia/nemotron-3.5-super-vl:free` |
| `DATABASE_URL` | `sqlite:////app/data/oma_dom.db` |

5. Click **Create Web Service** and wait for the first deploy (~5–10 min).

Optional: **New** → **Blueprint** → select repo → uses `render.yaml` (still set `GEMINI_API_KEY` in the dashboard).

## 3. Check it works

After deploy, Render gives a URL like:

`https://oma-dom-api.onrender.com`

Open:

- `https://oma-dom-api.onrender.com/docs`
- `https://oma-dom-api.onrender.com/api/v1/health`
- `https://oma-dom-api.onrender.com/api/v1/products`

## 4. Flutter (real phone)

```dart
OmaApiClient(baseUrl: 'https://oma-dom-api.onrender.com');
```

Use **HTTPS**, no port. No auth.

## Free plan notes

- Service **sleeps after ~15 minutes** idle → first request can take 30–60s.
- SQLite + uploads are **ephemeral**: redeploy recreates DB; catalog is re-seeded from `data/products/products.json` + images/GLBs baked into the image.
- Room photo uploads do **not** survive redeploys on free tier (fine for MVP demos).
- Never commit `.env` / API keys.
