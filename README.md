# Boundless Boston Navigator

**New here?** Read [CONTRIBUTING.md](CONTRIBUTING.md) for the design, workflow and current progress.

A newcomer-facing Boston night planner. The app combines venue fit, walk estimates, transit context, weather, and neighborhood signals, while showing when information is demo, live, cached, or unavailable.

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

Open the Vite URL (normally `http://localhost:5173`). The frontend proxies `/api` to port 8000. The API docs are at `http://localhost:8000/docs`.

## Current implementation

- `backend/app/main.py`: FastAPI query, recommendations, neighborhood, and health endpoints; request validation; scoring; SQLite public response TTL cache; demo fixtures.
- `backend/app/tiktok.py`: TikTok Login Kit OAuth + Display API taste preferences (personalization only).
- `src/`: React/Vite UI with responsive search, saved places (`localStorage`), TikTok connect, score breakdowns, weather override, source status, and attribution presentation.
- `scoring/weights.yaml`: declared scoring weights (includes `taste`).
- `docs/architecture/` and `docs/SOURCES.md`: architecture and data handling decisions.

`APP_MODE=demo` is the default and uses clearly labeled synthetic fixtures. Live mode is opt-in with `APP_MODE=live`. Live Tier 1 paths are implemented for Google Places, MBTA stops/routes/schedules/predictions/alerts, National Weather Service hourly forecasts, and Boston CKAN 311 and active food-establishment license data. Boston CKAN resource IDs are discovered dynamically with `package_show`. Transit eligibility uses paired scheduled trips, with prediction confirmation where available, or an explicitly approximate walking fallback. Google Places requires `GOOGLE_MAPS_API_KEY`; without it, live mode returns no Google candidates instead of substituting fixtures. Set `BOSTON_311_PACKAGE` and `BOSTON_LICENSE_PACKAGE` to override the CKAN package slugs.

### TikTok personalization (optional)

Register an app at [TikTok for Developers](https://developers.tiktok.com/), enable Login Kit + TikTok API with scopes `user.info.basic` and `video.list`, and set the redirect URI to your frontend-origin callback (local default `http://localhost:5173/api/tiktok/callback` so the Vite proxy sets the session cookie on the UI host). Set `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, and `TIKTOK_REDIRECT_URI`. In demo mode, **Connect TikTok** uses fixture taste tags without credentials. TikTok is never used for venue discovery.

## Train reliability (Tiger Data)

Cards add "ran 3 min late on average in the last 12 h (8 trains)" next to the last train back, from MBTA predictions recorded into a Tiger Data (TimescaleDB) hypertable.

1. Create a Tiger Data service and run `backend/migrations/0003_train_reliability.sql` in its SQL editor (it calls `create_hypertable`).
2. Set `TIGER_DATABASE_URL` (the service's `postgres://` connection string) in `.env` and on the Render API service.
3. Keep the recorder running. On Render it runs inside the API when `RUN_RECORDER=1` (until `RECORDER_UNTIL`), and `.github/workflows/keep-awake.yml` pings the API every 5 minutes so the free plan doesn't sleep. Locally: `cd backend && ../.venv/bin/python -m app.reliability`. It makes one MBTA call a minute for 12 stations (`STATIONS` in `backend/app/reliability.py`); run only one recorder at a time.

`GET /api/reliability?route=Red&stop=place-harsq&direction=1` returns the last 12 hours' average for that direction and a 15-minute `time_bucket` timeline (`hours=1..24`). Only trains that have left count (they dropped out of the MBTA feed), and cards show the average only after 5 of them, in the same direction as the last train back. Trips the MBTA runs without a schedule (for example "added" trips during a shuttle) are skipped, since there is no scheduled time to compare against.

## Deploy

### Docker (web UI and API)

Requires Docker with Linux container support (Docker Desktop on Windows/macOS,
or Docker Engine on Linux). No host Python or Node.js installation is needed.
From the repository root:

```sh
docker build -t boundless-boston .
docker run --rm --name boundless-boston -p 8000:8000 -v boundless-data:/app/.cache boundless-boston
```

Open `http://localhost:8000`; API docs are at `http://localhost:8000/docs`.
The image defaults to demo mode, serves the compiled UI and API from one origin,
runs as UID/GID 10001, and checks `/api/health` automatically. The named volume
retains the response cache and TikTok sessions across container restarts. Bind
mounts must be writable by UID 10001.

For live providers, copy `.env.example` to `.env`, configure `APP_MODE=live`
and provider keys, and add `--env-file .env` before the image name in the run
command. Set `CORS_ORIGINS` to your web origin (locally `http://localhost:8000`)
and `TIKTOK_REDIRECT_URI` to that origin plus `/api/tiktok/callback`. Register
the same callback with TikTok; set `TIKTOK_COOKIE_SECURE=true` when serving over
HTTPS. Use a reverse proxy or hosting platform for TLS. Secrets and local
databases are excluded from the build context.

`PORT` defaults to 8000. To change it, set both the environment variable and
mapping, for example `-e PORT=8080 -p 8080:8080`, and update the origin/callback
settings to match. Only Docker and network access for building and live
providers are required; native Expo mobile builds remain separate.

`dependencies.txt` contains Python runtime dependencies;
`backend/requirements.txt` includes it plus pytest for development. Frontend
dependencies use a frozen `pnpm-lock.yaml`. Base images support AMD64 and ARM64;
publish both with a configured Buildx builder using
`docker buildx build --platform linux/amd64,linux/arm64 -t YOUR_REGISTRY/boundless-boston --push .`.

### Persistent local demo (Windows)

After installing the Python and frontend dependencies and configuring `.env`,
run `npm run demo` once. It starts the API and frontend in the background at
http://127.0.0.1:5173 and returns when both are healthy. Repeating the command
is safe. The supervisor restarts crashed processes and restarts services after
three failed health checks following a 60-second startup grace period.
Use `npm run demo:status` to check services and `npm run demo:stop` to stop them.
Logs are in `.cache/demo/`. Processes survive closing the launching terminal;
run the command again after rebooting or signing out of Windows.

### Hosted services

- **API:** Render, from `render.yaml` (free web service, `APP_MODE=live`). Set `GOOGLE_MAPS_API_KEY` and `MBTA_API_KEY` in the Render dashboard. The free plan sleeps when idle, so the first request after a pause can take about a minute.
- **Frontend:** Render static site `boundless-boston-web` (also in `render.yaml`). A rewrite sends `/api/*` to `https://boundless-boston-api-5ze8.onrender.com`, so no CORS setup is needed.

## Neon

In live mode (`APP_MODE=live`), `/api/query` first reads nearby OpenStreetMap
places from `public.catalog_venues` in Neon. Set the backend's `DATABASE_URL`
to the pooled connection for the production branch containing that catalog,
and install `backend/requirements.txt`. The frontend already calls this endpoint;
database credentials stay on the server. `/api/health` includes `neon.catalog`
after a search. Eligible places must have known opening hours that include the
requested time. If the catalog is unavailable or yields no eligible candidates,
discovery falls back to Google Places and then the bundled OSM snapshot.
Demo mode continues to use fixtures. Redeploy the API after changing its code
or environment; no frontend API URL change is required.

`neon.ts` remains the Neon project configuration. The application API is FastAPI and needs a Python 3.12 runtime; it is not packaged as a Neon Function. Deploying the database/service requires a configured Neon project and a compatible Python hosting target. No credentials or deployment identifiers belong in the frontend bundle.

Recommendation snapshots are persisted to Neon when the API has a `DATABASE_URL`. The application uses the pooled URL for request traffic; apply `backend/migrations/0002_recommendations.sql` with a direct connection when setting up another branch. Each `/api/query` response remains available if Neon is temporarily unavailable and includes a `storage` status for observability.
