# Contributing to Boundless Boston Navigator

Start here. This page covers what the app does, how it fits together, how to ship a change, and where things stand. **Keep the Progress section current**: update it in the same PR as your change.

_Last updated: 2026-11-21_ · **Live site:** https://boundless-boston-web-5ze8.onrender.com · **API:** https://boundless-boston-api-5ze8.onrender.com

## What it does

You give it a place, a time, a budget and how long you'll travel (walking, or walking + the T). It returns up to 8 places that are **open then, within budget, and reachable there and back**, and it shows where every piece of data came from (live, cached, demo or unavailable). Fixture data is never shown as live.

## How it fits together

```text
  You (browser)
      │  boundless-boston-web-5ze8.onrender.com   (React + Vite, Render static site)
      │  /api/*  ──rewrite──▶  boundless-boston-api-5ze8.onrender.com
      ▼
  ┌───────────────────────── FastAPI backend (backend/app/main.py) ─────────────────────────┐
  │  rate limit (30/min per visitor, 120/min site)  →  search pipeline  →  JSON + sources    │
  │  every outside call goes through request_json: timeout · 1 retry · circuit breaker · cache│
  └──────────────────────────────────────────────────────────────────────────────────────────┘
      │
      ├─ Places ......... Google Places (live)  ── if it returns nothing ──▶  OpenStreetMap snapshot (backup)
      ├─ Transit ........ MBTA V3 (stop list fetched daily; nearest stops found locally)
      ├─ Walking ........ OpenRouteService (non-Google venues only) · otherwise straight-line "(approx.)"
      ├─ Weather ........ National Weather Service (api.weather.gov)
      ├─ Events ......... Red Sox (MLB) + Bruins (NHL) home games  ·  Ticketmaster (pending approval)
      ├─ Language ....... Gemini: typed request → filters; "Why this?" one-liner
      ├─ Taste .......... TikTok Login Kit (opt-in) + saved places → preference_tags (not venue discovery)
      └─ Neighborhood ... Boston Open Data (311 requests, business licenses)
```

### One search, step by step

```text
 "cheap cocktails,       ┌─────────┐   ┌────────────┐   ┌──────────────┐   ┌───────┐   ┌──────────┐   ┌─────────┐
  20 min, Walk + T"  ──▶ │ 1 PARSE │──▶│ 2 FIND     │──▶│ 3 HARD       │──▶│4 REACH│──▶│ 5 SCORE  │──▶│ 6 SHOW  │
                         │ Gemini  │   │ Google or  │   │   FILTERS    │   │walk or│   │ 0–1 each │   │ top 8 + │
                         │ → $ bar │   │ OSM backup │   │ open? budget?│   │ T trip│   │ weighted │   │ "Why?"  │
                         │ 20 min  │   │ ≤20 places │   │ type?        │   │fits?  │   │ sum      │   │ sources │
                         └─────────┘   └────────────┘   └──────────────┘   └───────┘   └──────────┘   └─────────┘
```

1. **Parse**: Gemini turns free text into filters (budget, minutes, type). If Gemini is off or fails, simple rules do it.
2. **Find**: up to 20 nearby places from Google Places. If Google returns nothing (no key, quota, outage), the bundled OpenStreetMap snapshot is used instead, and the two are never mixed.
3. **Hard filters** (pass or drop): open at the chosen time (unknown hours = dropped), price ≤ budget (OSM backup: price unknown is allowed), matches the type if one was asked for.
4. **Reach** (pass or drop): see "How ranking works" below.
5. **Score**: six parts, weighted (below), including optional taste when preference tags are present.
6. **Show**: the top 8 by score (ties go to the shorter walk), each with its full breakdown and data sources.

## How ranking works

### Step 1: who gets in (pass/fail)

```text
   all nearby places
          │
          ▼
   ┌──────────────┐  no   ┌──────────────┐  no   ┌──────────────┐  no   ┌──────────────────────────────┐  no
   │ open at that │──x    │ within your  │──x    │ right type   │──x    │ you can get there AND back   │──x
   │ time?        │       │ budget?      │       │ (if asked)?  │       │ within your trip-time limit? │
   └──────┬───────┘       └──────┬───────┘       └──────┬───────┘       └──────────────┬───────────────┘
          │ yes                  │ yes                  │ yes                          │ yes
          └──────────────────────┴──────────────────────┴──────────────────────────────▶  eligible → scored
```

**"Get there and back"** means one of:
- **Walk**: the walk fits your limit (minutes, from OpenRouteService or the labeled straight-line estimate).
- **Walk + T** (default): an MBTA trip (one line, or two subway lines with one change) where *walk to the stop + wait + ride(s) + walk to the place* fits your limit, **and** a train runs back later that night (at least 1 h after you set out, before service ends). If walking and the T both work, the faster one wins. "Walk only" ignores the T.

### Step 2: the score (0 to 1)

Each eligible place gets six sub-scores between 0 and 1. The final score is their weighted average, with base weights from `scoring/weights.yaml`:

| Part | Weight | What it measures | How |
|---|---:|---|---|
| **Momentum** | 15% | Is it getting popular? | Review growth over 30 days (max +10 → 1.0). *Not available in live mode, because Google's terms forbid storing review snapshots.* |
| **Quality** | 25% | Is it good? | Rating adjusted for review count, so a 5.0 from 3 reviews doesn't beat a 4.6 from 5,000: `(n/(n+50))·rating + (50/(n+50))·median`, ÷ 5 |
| **Reach** | 20% | How sure is the trip? | 1.0 = live MBTA prediction confirms the ride there · 0.5 = scheduled T trip or walking |
| **Events** | 15% | Is something happening nearby? | Red Sox/Bruins home games within ½ mile, from 3 h before to 3 h after (3+ games → 1.0) |
| **Weather** | 15% | Does the place suit the weather? | Rain ≥ 50% or below 40°F: indoor 1.0, outdoor 0.0. Otherwise everything 0.5 |
| **Taste** | 10% | Does it match your vibe? | Jaccard overlap of venue categories with `preference_tags` from TikTok and/or saved places. Missing tags drop out. |

**Missing data doesn't count against a place.** If a part has no data, its weight is set to 0 and the remaining weights are scaled up to total 100%:

```text
  base weights        momentum 15 │ quality 25   │ reach 20 │ events 15 │ weather 15 │ taste 10
  live (no taste)     momentum  – │ quality ~33 │ reach ~27 │ events 20 │ weather 20 │ taste –   momentum+taste missing
  OSM backup          momentum  – │ quality  –   │ reach ~40 │ events 30 │ weather 30 │ taste –   no ratings either
```

### Why these metrics (and how sure we are)

The core parts come from the original design (`docs/architecture/02-data-contracts-and-scoring.md`), which used 30/30/20/10/10. On 2026-11-21 the weights were changed to 20/30/20/15/15 so games and rain visibly matter, then taste 10% was added (15/25/20/15/15/10). They are **judgment calls, not tuned on data**: there has been no user testing or A/B comparison yet.

| Part | Why it's there |
|---|---|
| Quality | "Is it good?" A Bayesian average (the IMDb idea) with a 50-review prior, so a handful of 5-star reviews can't beat thousands of 4.6s. |
| Momentum | "Is it buzzing?" Meant to surface places on the rise. It can't be computed in live mode, because Google's terms bar storing review counts over time. |
| Reach | The core promise: you can get there **and back**. A trip confirmed by a live MBTA prediction counts as more certain than a schedule. |
| Events | Nightlife energy (a game letting out nearby). A small nudge, not a decider. |
| Weather | Comfort: indoor places get a lift when it's raining or cold. |
| Taste | Personalization from optional TikTok connect and saved places; never invents venue discovery from TikTok. |

**Known effects of these choices:** in live mode quality still carries the most weight when momentum/taste are missing. Weather and events stay visible so rain and games reorder results. In the OSM backup most places tie (no ratings), and ties go to the shorter walk.

**To change them**, edit `scoring/weights.yaml` (the weights must sum to 1). Scores, breakdowns and the "Why this?" view follow automatically. If you retune, note the reason in your PR and update the tables here.

### Worked example (live, 8 p.m., bars near North Station, Google over quota so OSM backup)

```text
  Sullivan's Tap      reach   0.50 × 40% = 0.200   (walkable)
                      events  0.33 × 30% = 0.100   (Bruins vs Capitals at TD Garden, 7:00 PM, 1 of 3 → 0.33)
                      weather 0.50 × 30% = 0.150   (clear, 53°F → neutral)
                      ─────────────────────────────
                      score            = 0.450  → shown as 45
```

Cards also show any counted game ("Game nearby: Bruins vs Capitals at TD Garden, 7:00 PM"). Every card's **"Why this?"** shows exactly this breakdown: each part's value, its effective weight, its sources, and "not used (reason)" for parts without data.

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
   - Render has no GitHub access, so CI deploys instead: after every check passes on `main`, the `deploy` job in `.github/workflows/ci.yml` calls the Render deploy hooks (repo secrets `RENDER_DEPLOY_HOOK_WEB` and `RENDER_DEPLOY_HOOK_API`). Until those secrets are set, it skips, and you deploy from the Render dashboard.
   - Check `https://boundless-boston-api-5ze8.onrender.com/api/sources/health`.

**Secrets:** keys live only in `.env` (git-ignored) and on Render's Environment page. Never put them in the frontend, a commit or chat.

## Progress

### APIs

| Source | Tier | Status |
|---|---|---|
| Google Places | 1 | Live on Render (Maps Demo Key: testing only, add billing before launch) |
| MBTA | 1 | Live (stops-radius and stairway-node bugs fixed) |
| NWS weather | 1 | Live (replaced Open-Meteo, which returned HTTP 429 to Render) |
| Boston CKAN | 1 | Live |
| Gemini parser | 2 | Live: free text → filters, with a rule-based fallback |
| Gemini "why this place" | 2 | On demand when "Why this?" opens (`POST /api/explain`); numbers are checked against the facts; separate breaker `gemini_explain` |
| Ticketmaster | 2 | Partly done: Built on `b/ticketmaster`, waiting for API key approval |
| TikTok Login Kit + Display API | 2 | Partly done: On `b/tiktok-taste-and-saves`: OAuth + taste tags + demo fixtures. Personalization only (not venue discovery). Needs Live/Sandbox credentials, HTTPS redirect, and Render env to connect a real account. |
| Sports schedules (events) | 2 | Red Sox (MLB Stats API) and Bruins (NHL) home games at Fenway and TD Garden, no key. Games from 3 h before to 3 h after the search time count as events for places within 0.5 mi. Celtics are not included: NBA's feed blocks automated access. MLB data is © MLB Advanced Media and its notice allows individual, non-commercial use, so review it before any commercial launch. |
| OpenRouteService (real walk times) | 2 | Partly done: Wired, but **only for non-Google venues** (none until Overpass): Google Maps ToS 3.2.3(a)/(c) bar sending Places coordinates to it. Google venues show the straight-line estimate "(approx.)". Google's own Routes API is the compliant option, but it needs billing (the demo key gets 403). |
| OpenStreetMap (backup) | 2 | Used only when Google Places returns nothing (no key, quota, outage); never mixed with Google. Reads a bundled snapshot (`backend/data/osm_venues.json`, refreshed with `scripts/refresh_osm_snapshot.py`) because live Overpass takes 30–60 s. No ratings or prices ("PRICE UNKNOWN"); common `opening_hours` forms are parsed, the rest count as unknown. |
| Yelp | 2 | Skipped: no free tier (paid plans from ~$229/month), and the 30-day trial forbids a public launch. Google already provides ratings. |
| Census ACS | 3 | Not started: Stretch goal |

### Platform

- CI on PRs: pytest, typecheck, build, and a Playwright demo walkthrough (`e2e/demo.spec.ts`, demo fixtures, no keys).
- Backend on Render, free plan, Oregon. It sleeps when idle, so the first request can take about a minute.
- Frontend on a Render static site (`boundless-boston-web-5ze8`), with `/api/*` rewritten to the API (POST bodies and query strings pass through). It replaces Vercel.
- Partly done: deploys from CI through Render deploy hooks; needs the two `RENDER_DEPLOY_HOOK_*` repo secrets set by the repo owner.
- Tests: 57 backend tests (hours, weather, events, parser, scoring, transit, OSM backup, rate limits) + 9 Playwright demo steps. Large parts of `main.py` (live adapters) are still only tested by hand.

### Google Maps terms

- Removed the OSM/Leaflet map: ToS 3.2.3(e) and SST 14.2 bar Places content "with or near a non-Google Map".
- Google coordinates are no longer sent to OpenRouteService.
- No coordinates go to the MBTA API: the full stop list (open data, ~8k stops) is fetched daily and the nearest stops are found locally; only stop IDs are sent for routes and schedules.
- Caution: Gemini: the explain endpoint sends Places facts to Gemini, and on the free tier Google may use that data to improve models, which risks ToS 3.2.3(c)(vii). Use the paid Gemini tier before launch.

### Scoring (Area A)

- Reach is a hard filter: walk **or** a door-to-door T trip with a train back, within the trip-time limit; the faster wins. "Walk only" mode ignores the T.
- T search: the 3 nearest stations plus the 2 nearest bus stops, subway first, at most 6 routes per place; line names and colors, plus the last train home on cards.
- Parts with no data get weight 0 and the rest are rescaled (see "How ranking works").
- Weights and thresholds load from `scoring/weights.yaml`; quality uses the true median.
- Taste component (0.10): Jaccard overlap of venue categories with `preference_tags` from TikTok and/or saved-place categories; missing tags drop out and rescale.
- One transfer between subway lines (at Park Street, Downtown Crossing, State, Government Center, Haymarket or North Station) when no single line works, e.g. "Orange Line → Red Line, change at Downtown Crossing". It allows 3 minutes to change, and the trip home is also two legs.
- MBTA alerts only block a route when they are active at the trip time (a scheduled weekend suspension no longer blocks tonight's trains).

### Product / UX

- College Atlas: separate lazy-loaded view at `/#atlas`, 19 searchable campus centers, 3D building map, 2D toggle, river overview, and a searchable directory fallback without WebGL. Map data requires internet; venue results are not displayed in the Atlas.

- Saved places: heart toggle persists in browser `localStorage`; Saved panel lists/unsaves; categories feed taste tags.
- Partly done: TikTok Connect UI + taste chips: demo path works locally; real account connect needs deployed callback, Render TikTok env vars, and TikTok Sandbox/Live setup.

### Up next

1. Finish TikTok real-account path: merge this branch, set Render `TIKTOK_*` + matching HTTPS redirect, verify Sandbox OAuth end-to-end.
2. Ticketmaster: test live and open the PR once the key is approved (adds concerts and shows on top of the Red Sox/Bruins games).
3. Refresh the OSM snapshot now and then: `.venv/bin/python -I scripts/refresh_osm_snapshot.py` (public Overpass servers are slow; the script tiles and retries, and keeps the old file on failure).
4. Move Gemini to the paid tier before launch (Places facts on the free tier; see Google Maps terms above).
5. Rate limits: `/api/query`, `/api/recommendations` and `/api/explain` allow 30/min per visitor and 120/min site-wide (429 + Retry-After).
6. Before launch: Google billing, consider moving Render to Virginia, and the security and accessibility checks in doc 05.
