# T-Recs (Boundless Boston Navigator)

A Boston night planner for students: places that are **open at your time, in budget, and reachable there and back**, by foot or by the T before the last train home. Every number shows where it came from (live, cached, demo or unavailable).

**Live:** https://boundless-boston-web-5ze8.onrender.com · **API:** https://boundless-boston-api-5ze8.onrender.com

- [CONTRIBUTING.md](CONTRIBUTING.md): how to ship a change, and current progress.
- [docs/DESIGN.md](docs/DESIGN.md): design choices and exactly how places are ranked.
- [docs/SOURCES.md](docs/SOURCES.md) and [docs/architecture/](docs/architecture/): data sources and architecture.

## Run locally

Requires Python 3.12 and Node.js 20+.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
APP_MODE=demo uvicorn app.main:app --app-dir backend --reload --port 8000
```

In another terminal:

```sh
pnpm install
pnpm dev
```

Open `http://localhost:5173`. The frontend proxies `/api` to port 8000; API docs are at `http://localhost:8000/docs`.

`APP_MODE=demo` (the default) uses clearly labeled fixtures and needs no keys. For live data, copy `.env.example` to `.env`, set `APP_MODE=live`, and add the keys you have. Live mode never substitutes demo fixtures: a missing key turns that source off, and without a Google key places come from the Neon catalog or the bundled OpenStreetMap snapshot. MBTA, the National Weather Service, Boston Open Data and the Red Sox/Bruins schedules need no key.

| Variable | Used for |
|---|---|
| `GOOGLE_MAPS_API_KEY` | Places, ratings, hours, prices |
| `MBTA_API_KEY` | Higher MBTA quota (works without one) |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Free-text search (rule-based fallback) and "Why this?" (template fallback) |
| `ORS_API_KEY` | Street-routed walk times (straight-line estimate without it) |
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI`, `TIKTOK_COOKIE_SECURE` | Optional TikTok taste tags (see below) |
| `DATABASE_URL` (or `NEON_DATABASE_URL`) | Optional Neon catalog and saved runs |
| `TIGER_DATABASE_URL` | Optional last-train reliability |
| `BOSTON_311_PACKAGE`, `BOSTON_LICENSE_PACKAGE` | Override the Boston Open Data package slugs |

`.env.example` also lists `CORS_ORIGINS`, `CACHE_DB`, `TIKTOK_SESSION_DB` and `BOSTON_CKAN_URL`, with working defaults.

**Tests:** `cd backend && ../.venv/bin/python -m pytest -q`, then `pnpm typecheck` and `pnpm build`. For the browser tests, run `pnpm exec playwright install chromium` once, then `pnpm e2e` (it uses `.venv/bin/python` unless `PYTHON` is set).

## What's where

- `backend/app/main.py`: FastAPI endpoints, validation, the search pipeline, MBTA round trips, scoring, caching and demo fixtures.
- `backend/app/reliability.py`: Tiger Data recorder and reliability queries.
- `backend/app/tiktok.py`: TikTok Login Kit and taste tags.
- `backend/app/neon.py`: optional Neon catalog and run storage.
- `src/`: React + Vite UI.
- `features/college-atlas/`: the Map view.
- `scoring/weights.yaml`: scoring weights and thresholds.

## TikTok personalization (optional)

TikTok only adds taste tags; it is never used to find venues. In demo mode, **Connect TikTok** uses fixture tags with no credentials.

For a real account, register an app at [TikTok for Developers](https://developers.tiktok.com/), enable Login Kit and the TikTok API with scopes `user.info.basic` and `video.list`, and register the redirect URI on the frontend's origin, locally `http://localhost:5173/api/tiktok/callback` (through the Vite proxy, so the session cookie lands on the UI host). Set `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` and `TIKTOK_REDIRECT_URI`, and `TIKTOK_COOKIE_SECURE=true` when serving over HTTPS.

## Train reliability (Tiger Data)

Cards add "ran 3 min late on average in the last 12 h (8 trains)" next to the last train back.

1. Create a Tiger Data service and run `backend/migrations/0003_train_reliability.sql` in its SQL editor (it calls `create_hypertable`).
2. Set `TIGER_DATABASE_URL` in `.env` and on the Render API service.
3. Run exactly one recorder. On Render it runs inside the API (`RUN_RECORDER=1` in `render.yaml`) until `RECORDER_UNTIL`. Locally: `cd backend && ../.venv/bin/python -m app.reliability`. It makes one MBTA call a minute for 12 stations.

`GET /api/reliability?route=Red&stop=place-harsq&direction=1&hours=12` returns a 15-minute `time_bucket` timeline for `hours=1..24` (both directions), plus the card average for that direction when `hours=12`. Only trains that have left count, and cards show the average only after 5 of them. Trips with no schedule (for example during a shuttle) are skipped.

Render's free plan sleeps after 15 idle minutes, which pauses the recorder. `.github/workflows/keep-awake.yml` pings the API, but GitHub runs scheduled jobs late or skips them, so expect gaps. Recording and pinging end on 2026-11-24 00:00 Boston time: to extend, change `RECORDER_UNTIL` (on Render and in `render.yaml`) and the date in `keep-awake.yml` together.

## Deploy

- **Render** (`render.yaml`): the API service `boundless-boston-api` (free web service, `APP_MODE=live`) and the static site `boundless-boston-web`, which rewrites `/api/*` to the API. They're served at the `-5ze8.onrender.com` URLs above. Keys go in the Render dashboard.
- **Auto-deploy:** after every merge to `main`, once CI passes, `.github/workflows/ci.yml` calls the Render deploy hooks (repo secrets `RENDER_DEPLOY_HOOK_WEB` and `RENDER_DEPLOY_HOOK_API`) for that exact commit.
- **Docker** (one container for UI and API):

  ```sh
  docker build -t boundless-boston .
  docker run --rm -p 8000:8000 -v boundless-data:/app/.cache boundless-boston
  ```

  Open `http://localhost:8000`. It defaults to demo mode; add `--env-file .env` for live keys. Set `CORS_ORIGINS` to the origin and `TIKTOK_REDIRECT_URI` to `<origin>/api/tiktok/callback`. The container runs as UID/GID 10001, so bind mounts must be writable by it; the volume keeps the cache and TikTok sessions. To change the port, set both `-e PORT=8080 -p 8080:8080` and update the origin and callback. Python runtime dependencies are in `dependencies.txt` (`backend/requirements.txt` adds pytest).
- **Windows demo:** with the venv at `.venv`, `npm run demo` starts the API and UI in the background at `http://127.0.0.1:5173` and restarts them if they crash (`npm run demo:status`, `npm run demo:stop`; logs in `.cache/demo/`).

## Neon (optional)

With `DATABASE_URL` set in live mode, search first reads nearby OpenStreetMap places from `public.catalog_venues`, then falls back to Google Places and the bundled OSM snapshot. Recommendation runs are saved there too: use the pooled connection for the app, and a direct one to apply `backend/migrations/0002_recommendations.sql`. `/api/health` reports Neon's status. Without it, everything still works. `neon.ts` is the Neon project config.
