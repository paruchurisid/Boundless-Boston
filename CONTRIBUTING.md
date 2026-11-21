# Contributing to Boundless Boston Navigator

Start here. This page covers what the app does, how it fits together, how to ship a change, and where things stand. **Keep the Progress section current**: update it in the same PR as your change.

_Last updated: 2026-11-21_ · **Live site:** https://bostonboundless.vercel.app · **API:** https://boundless-boston-api-5ze8.onrender.com

## What it does

You give it a place, a time, a budget and how far you'll walk. It returns 5–8 places that are **open then, within budget, and reachable there and back**, and it shows where every piece of data came from (live, cached, demo or unavailable). Fixture data is never shown as live.

## How it fits together

```text
Browser (React + Vite)          Vercel: static frontend; proxies /api/* to Render
   │  same-origin /api
FastAPI backend                 Render: backend/app/main.py
   │  every outbound call goes through request_json (retry, circuit breaker, SQLite cache)
   ├─ Google Places     venues, ratings, hours, price
   ├─ MBTA V3           stops, schedules, predictions → round-trip check
   ├─ NWS               hourly weather (api.weather.gov)
   ├─ Boston CKAN       311 requests and business licenses (neighborhood panel)
   ├─ Gemini            free text → filters (falls back to rules)
   ├─ OpenRouteService  street-routed walking minutes
   └─ Ticketmaster      nearby events (branch built, waiting for key approval)
```

**One search, step by step:**
1. **Parse** the free text into filters (Gemini, or the rule-based fallback).
2. **Candidates**: Google Places, or fixtures in demo mode.
3. **Hard filters**: open at the requested time, within budget, within walking range.
4. **Reach**: MBTA round trip, or the walking fallback.
5. **Score**: momentum, quality, reach, events and weather, using the weights in `scoring/weights.yaml`.
6. **Return** the ranked list, the full score breakdown and `sources_used`.

The full design is in `docs/architecture/` (01–05). The source rules are in `docs/SOURCES.md`.

## Who owns what

| Area | Owner | Files |
|---|---|---|
| **A: recommendation logic** | Teammate A | Filters, reach rules, scoring (`score_venue`, `make_query` logic), `scoring/weights.yaml` |
| **B: platform and APIs** | Teammate B | Source adapters, `request_json`, CI, deploy (`render.yaml`, `vercel.json`) |

If you need to change the other person's area, tell them first.

## Run it locally

```sh
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cp .env.example .env          # add keys; leave empty for demo mode
set -a; . ./.env; set +a
APP_MODE=demo .venv/bin/uvicorn app.main:app --app-dir backend --reload --port 8000   # or APP_MODE=live
pnpm install && pnpm dev      # pnpm 10; open http://localhost:5173
```

Demo mode needs no keys. Live mode uses whichever keys are set, and any source without a key shows as `disabled`.

## How to ship a change

1. **Branch** off `main` (`a/...` or `b/...`). Never push to `main`.
2. **Test**: `cd backend && ../.venv/bin/python -m pytest -q`, plus `pnpm typecheck && pnpm build`. Add a small test for new logic.
3. **Open a PR** that says what changed, how you tested it, and the risks. CI runs pytest, the typecheck and the build.
4. **Review**: get approval before merging. We squash-merge.
5. **Deploy**:
   - Vercel deploys the frontend on its own.
   - **Render auto-deploy is currently not firing**, so trigger a deploy from the Render dashboard (or through the Render MCP) after merging.
   - Check `https://boundless-boston-api-5ze8.onrender.com/api/sources/health`.

**Secrets:** keys live only in `.env` (git-ignored) and on Render's Environment page. Never put them in the frontend, a commit or chat.

## Progress

### APIs

| Source | Tier | Status |
|---|---|---|
| Google Places | 1 | ✅ Live on Render (Maps Demo Key: testing only, add billing before launch) |
| MBTA | 1 | ✅ Live (stops-radius and stairway-node bugs fixed) |
| NWS weather | 1 | ✅ Live (replaced Open-Meteo, which returned HTTP 429 to Render) |
| Boston CKAN | 1 | ✅ Live |
| Gemini parser | 2 | ✅ Live: free text → filters, with a rule-based fallback |
| Gemini "why this place" | 2 | ✅ On demand when "Why this?" opens (`POST /api/explain`); numbers are checked against the facts; separate breaker `gemini_explain` |
| Ticketmaster | 2 | 🟡 Built on `b/ticketmaster`, waiting for API key approval |
| OpenRouteService (real walk times) | 2 | ✅ One matrix call per search, before the walk filter; falls back to the straight-line estimate (labeled approx.) |
| OpenStreetMap Overpass | 2 | ⬜ Not started (no key; needs the dedupe rules in doc 02) |
| Yelp | 2 | ⬜ Deferred (strict usage terms) |
| Census ACS | 3 | ⬜ Stretch goal |

### Platform

- ✅ CI on PRs: pytest, typecheck and build (pnpm 10.34.9).
- ✅ Backend on Render, free plan, Oregon. It sleeps when idle, so the first request can take about a minute.
- ✅ Frontend on Vercel at https://bostonboundless.vercel.app, with `/api` proxied to Render. The Vercel Git integration deploys on its own. A second Vercel project named `backend` also exists; it's unused, since the API runs on Render.
- 🟡 Render auto-deploy: needs Render's GitHub app to have access to the repo.
- ⬜ Tests cover opening hours, weather, events and the parser only; `main.py` is mostly untested.

### Known issues (Area A)

- **Transit never adds reach.** Venues beyond walking range are removed before the MBTA check runs, so every result says "walk fallback". The reach filter should be "walk **or** MBTA round trip".
- **Scores top out around 0.4.** Momentum (0.30) is always 0 in live mode, and events (0.10) is 0 until Ticketmaster lands. Spread unused weight over the other components.
- **"Live round trip" almost never shows.** The return trip is 3+ hours away, beyond MBTA's prediction window.
- **`weights.yaml` isn't loaded.** The weights are hardcoded in `score_venue`.

### Up next

1. Ticketmaster: test live and open the PR once the key is approved.
2. Area A: reach filter and weight fixes (above).
3. Consider a per-IP rate limit on `/api/explain` and `/api/query` (Gemini cost).
4. Before launch: Google billing, consider moving Render to Virginia, and the security and accessibility checks in doc 05.
