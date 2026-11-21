# Contributing to Boundless Boston Navigator

Start here. This page covers what the app does, how it fits together, how to ship a change, and where things stand. **Keep the Progress section current**: update it in the same PR as your change.

_Last updated: 2026-11-21_ · **Live site:** https://boundless-boston-web-5ze8.onrender.com · **API:** https://boundless-boston-api-5ze8.onrender.com

## What it does

You give it a place, a time, a budget and how far you'll walk. It returns 5–8 places that are **open then, within budget, and reachable there and back**, and it shows where every piece of data came from (live, cached, demo or unavailable). Fixture data is never shown as live.

## How it fits together

```text
Browser (React + Vite)          Render static site: CDN frontend; rewrites /api/* to the API
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
| **B: platform and APIs** | Teammate B | Source adapters, `request_json`, CI, deploy (`render.yaml`) |

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
2. **Test**: `cd backend && ../.venv/bin/python -m pytest -q`, plus `pnpm typecheck && pnpm build`, plus `pnpm e2e` (a Playwright demo walkthrough in demo mode; first run `pnpm exec playwright install chromium`). Add a small test for new logic.
3. **Open a PR** that says what changed, how you tested it, and the risks. CI runs pytest, the typecheck and the build.
4. **Review**: get approval before merging. We squash-merge.
5. **Deploy**:
   - Both the frontend and the API are in `render.yaml` (one Render Blueprint).
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
| OpenRouteService (real walk times) | 2 | 🟡 Wired, but **only for non-Google venues** (none until Overpass): Google Maps ToS 3.2.3(a)/(c) bar sending Places coordinates to it. Google venues show the straight-line estimate "(approx.)". Google's own Routes API is the compliant option, but it needs billing (the demo key gets 403). |
| OpenStreetMap (backup) | 2 | ✅ Used only when Google Places returns nothing (no key, quota, outage); never mixed with Google. Reads a bundled snapshot (`backend/data/osm_venues.json`, refreshed with `scripts/refresh_osm_snapshot.py`) because live Overpass takes 30–60 s. No ratings or prices ("PRICE UNKNOWN"); common `opening_hours` forms are parsed, the rest count as unknown. |
| Yelp | 2 | ⬜ Deferred (strict usage terms) |
| Census ACS | 3 | ⬜ Stretch goal |

### Platform

- ✅ CI on PRs: pytest, typecheck, build, and a Playwright demo walkthrough (`e2e/demo.spec.ts`, demo fixtures, no keys).
- ✅ Backend on Render, free plan, Oregon. It sleeps when idle, so the first request can take about a minute.
- ✅ Frontend on a Render static site (`boundless-boston-web-5ze8`), with `/api/*` rewritten to the API (POST bodies and query strings pass through). It replaces Vercel.
- 🟡 Render auto-deploy: needs Render's GitHub app to have access to the repo.
- ⬜ Tests cover opening hours, weather, events and the parser only; `main.py` is mostly untested.

### Google Maps terms

- ✅ Removed the OSM/Leaflet map: ToS 3.2.3(e) and SST 14.2 bar Places content "with or near a non-Google Map".
- ✅ Google coordinates are no longer sent to OpenRouteService.
- ⚠️ Gemini: the explain endpoint sends Places facts to Gemini, and on the free tier Google may use that data to improve models, which risks ToS 3.2.3(c)(vii). Use the paid Gemini tier before launch.

### Scoring (Area A)

- ✅ Reach is a hard filter: walk **or** MBTA round trip, so transit-only places can rank. The MBTA search considers the 3 nearest stations plus the 2 nearest bus stops.
- ✅ Components with no data get weight 0 and the rest are rescaled, so missing momentum or events no longer cap scores. Live scores now reach about 0.7–0.9.
- ✅ "Live round trip" = live-predicted outbound + scheduled return.
- ✅ Weights and thresholds load from `scoring/weights.yaml`; the quality prior uses the true median.
- ⬜ Direct routes only (no transfers). The walk to and from stops isn't counted against the walk limit.

### Up next

1. Ticketmaster: test live and open the PR once the key is approved.
1. Refresh the OSM snapshot now and then: `.venv/bin/python -I scripts/refresh_osm_snapshot.py` (public Overpass servers are slow; the script tiles and retries, and keeps the old file on failure).
2. Move Gemini to the paid tier before launch (Places facts on the free tier; see Google Maps terms above).
3. Consider a per-IP rate limit on `/api/explain` and `/api/query` (Gemini cost).
4. Before launch: Google billing, consider moving Render to Virginia, and the security and accessibility checks in doc 05.
