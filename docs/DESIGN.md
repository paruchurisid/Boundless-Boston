# Design choices and ranking

How T-Recs (Boundless Boston Navigator) decides what to show, why it is built the way it is, and exactly how places are ranked. Numbers here come from `scoring/weights.yaml` and `backend/app/main.py`; if they disagree, the code wins and this file should be updated.

## The problem we chose

Students new to Boston ask "where can I go tonight?", but the real question is **"where can I go tonight and still get home?"** Most apps answer the first half. We answer both: every result is open at the requested time, within budget, and reachable *there and back*, by foot or by the T before the last train.

## Core principles

1. **Never present guesses as facts.** Every number on a card is labeled with where it came from: live, cached, demo, or unavailable. Demo fixtures are never shown as live (the green dot is reserved for live data). Estimates say "approx.".
2. **Missing data drops out; it is never filled in.** If a source is down, its part of the score is removed and the rest is rescaled. We do not substitute fixtures in live mode, and "unavailable" is never shown as zero.
3. **Hard rules first, ranking second.** A place either qualifies (open, in budget, reachable both ways) or it doesn't. Scoring only orders places that already qualify.
4. **Explain every score.** "Why this?" shows each component, its value, its weight, and which parts were left out and why. There is never a bare score.
5. **Fail soft and stay fast.** Outside API calls have a timeout, one retry and a circuit breaker, and public data is cached, so one slow source cannot take down a search.
6. **Respect provider terms and privacy.** Google coordinates are never sent to non-Google services; user and venue coordinates are never sent to the MBTA (nearest stops are found locally); TikTok is used for taste only, never for finding venues.

## How a search works

```text
request (place, time, budget, trip-time limit, walk or walk + T, optional free text)
  │
  ├─ 1. Understand free text      Gemini → filters (budget, category, walk limit); rule-based parser as fallback
  ├─ 2. Find candidate places     Neon OSM catalog → Google Places → OpenStreetMap snapshot (first one that returns places)
  ├─ 3. Walk times                OpenRouteService for non-Google places; otherwise straight line × 1.3, labeled approx.
  ├─ 4. Context                   NWS forecast for the requested hour; Red Sox / Bruins home games
  ├─ 5. Hard filters              open at the requested time · price ≤ budget · matches category
  ├─ 6. Reachability              walk fits the limit, or an MBTA round trip with a train back fits it
  ├─ 7. Score and rank            weighted components (below), top 8
  ├─ 8. Last-train reliability    Tiger Data average delay for that line, station and direction (if 5+ trains)
  └─ 9. Respond                   cards + score breakdown + source status for every source used
```

### Step 6: reachability (the "get home" rule)

- **Walk only:** eligible if the estimated walk is within the trip-time limit.
- **Walk + T:** for places that are more than a short walk (over 15 minutes, or over the limit), we look for a real MBTA round trip:
  - the **same trip** must serve both stops in the right order (no stitching unrelated trains together);
  - you must be able to **walk to the stop before the train leaves**;
  - there must be a **train back** before the end of the MBTA service day (3:00 AM); for single-line trips we show the last or latest one;
  - lines with an **active** suspension or no-service alert at trip time are skipped (a future weekend closure does not block tonight);
  - if no single line works, we try **one transfer** between subway lines at the main hubs (Park Street, Downtown Crossing, State, Government Center, Haymarket, North Station), allowing 3 minutes to change platforms. Transfer trips show the train back but not a "last train" time.
- **Door-to-door time** = walk to the stop + wait + ride + walk to the venue. It has to fit the limit.
- If both walking and the T fit, the faster one wins.

## Ranking

Each qualifying place gets six component scores between 0 and 1. The final **FIT** score (0–100 on the card) is their weighted average.

| Component | Weight | What it measures | Source |
|---|---|---|---|
| Quality | 0.25 | Rating, adjusted for how many reviews back it up | Google Places |
| Reach | 0.20 | How confidently we can get you there and back | MBTA |
| Momentum | 0.15 | How fast the place is gaining reviews (is it buzzing now?) | Google Places (demo only, see below) |
| Events | 0.15 | Red Sox or Bruins home games nearby around your time | MLB / NHL schedules |
| Weather | 0.15 | Whether the place suits tonight's weather | National Weather Service |
| Taste | 0.10 | Overlap with your TikTok taste tags and saved places | TikTok (opt-in), saved places |

### Each component in detail

**Quality: Bayesian average rating.** A 5.0 with 3 reviews should not beat a 4.6 with 2,000. We shrink each rating toward the median rating of tonight's candidates, weighted by review count:

```text
quality = ( n/(n+m) × rating  +  m/(n+m) × median ) / 5        m = 50 reviews
```

A place with no rating (for example an OpenStreetMap place) has quality dropped for that place, marked "no rating", and its other weights are rescaled.

**Reach.** A confirmed MBTA round trip scores 1.0 when the outbound train is confirmed by a live prediction, and 0.5 when it is schedule-only. A walk-only result also scores 0.5. (Weights in `weights.yaml`: `mbta_round_trip: 1.0`, `walking_fallback: 0.5`.)

**Momentum: review velocity.** The 30-day change in review count, capped at 10 new reviews = 1.0. In live mode this is **dropped**, because Google's terms don't allow us to store review counts over time to compute it. It shows as "not used" rather than as zero. Demo fixtures carry a labeled value.

**Events: nearby games.** Home games that start within 3 hours of your time (or started up to 3 hours before) within half a mile (804.672 m) of the place. 3 or more games = 1.0. If the schedules can't be loaded, the component is dropped rather than scored 0.

**Weather.** "Bad weather" means at least a 50% chance of rain, or below 40°F, at the requested hour. In bad weather, indoor places score 1.0 and outdoor places 0.0. Otherwise everything scores 0.5. Indoor/outdoor comes from the place type. For Google places, parks and gardens are outdoor; restaurants, cafes, bakeries, bars, night clubs and food places are indoor; anything else is neutral. OpenStreetMap places are outdoor if they are a park and indoor otherwise.

**Taste: Jaccard overlap.** `|your tags ∩ place categories| / |your tags ∪ place categories|`. Your tags come from TikTok (if you connect it) and the categories of places you've saved, at most 12. If you have no tags, the component is dropped so it doesn't penalize anyone.

### Missing data rescales, never caps

If a component has no data (momentum in live mode, no TikTok tags, schedules down, a place with no rating), its weight is removed and the remaining weights are scaled back up to sum to 1. This is decided per place:

```text
weight_i = base_weight_i / sum(base weights of components that have data)
FIT      = sum(value_i × weight_i)
```

So a place is never capped at 85/100 just because one source was missing. Sources missing for the whole search (weather, game schedules, taste tags) drop out for every place alike; quality and momentum can differ from place to place.

### Worked example (demo data)

Tatte Bakery (rating 4.4, 820 reviews), demo mode, clear 55°F evening, no TikTok tags, no game within half a mile (the demo game is at TD Garden, about 1.3 km away), candidate median rating assumed to be 4.2:

| Component | Value | Weight after rescaling | Contribution |
|---|---|---|---|
| Quality | (820/870 × 4.4 + 50/870 × 4.2) / 5 = 0.878 | 0.25 / 0.90 = 0.278 | 0.244 |
| Reach | walking = 0.50 | 0.20 / 0.90 = 0.222 | 0.111 |
| Momentum | 7 new reviews / 10 = 0.70 | 0.15 / 0.90 = 0.167 | 0.117 |
| Events | 0 games = 0.00 | 0.167 | 0.000 |
| Weather | not adverse = 0.50 | 0.167 | 0.083 |
| Taste | dropped (no tags) | 0 | – |
| **FIT** | | | **0.555 → 55** |

Taste is dropped, so the other five weights (summing to 0.90) are rescaled. The 50 "prior" reviews pull Tatte's 4.4 slightly toward the 4.2 median; with only 10 reviews it would be pulled much further.

### Ties and limits

- Sort by FIT, highest first; ties go to the shorter walk (common with OpenStreetMap places, which lack ratings).
- Return the top 8. If none qualify, show exactly: "Nothing open and reachable at that time. Try an earlier hour or a higher budget."

## Last-train reliability (Tiger Data)

Cards add, next to "Last train back 12:47 AM", a line like **"ran 3 min late on average in the last 12 h (8 trains)"**.

- **Recording:** once a minute, the recorder (`backend/app/reliability.py`) asks the MBTA for live subway and light-rail predictions (not commuter rail or buses) at 12 stations students use (Harvard, Kendall/MIT, Park Street, Downtown Crossing, Kenmore, Fenway, BU Central, Copley, Back Bay, North Station, Assembly, Chinatown). That is one API call a minute. Each departure is stored next to its scheduled time in a TimescaleDB **hypertable** (`train_departures`, partitioned by scheduled time).
- **One row per train, kept current:** the recorder keeps updating a train's predicted time until it leaves, so the stored delay is the last prediction before departure, not an early guess.
- **Honesty rules:**
  - Only trains that have **already left** count. A late train still on its way would pull the average toward "on time".
  - Only the **same line, station and direction** as your train home.
  - Nothing is shown until **5 or more** trains have left. Fewer is noise.
  - Trips the MBTA runs **without a schedule** (for example "added" trips during a shuttle) are skipped, because there is no scheduled time to compare against.
  - The window is the **last 12 hours**, labeled as such, so a noon demo still covers the night before.
- **Endpoint:** `GET /api/reliability?route=&stop=&direction=&hours=` returns the card average for that direction (only for the default 12-hour window) plus a 15-minute `time_bucket` timeline for a "delay through the night" chart. The timeline combines both directions.
- **Fail-safe:** if Tiger is unreachable, searches skip it for a minute instead of each waiting out the 3-second timeout.

## Trust and data sources

| Source | Used for | When it's unavailable |
|---|---|---|
| Google Places | Places, ratings, hours, price | OpenStreetMap snapshot or Neon catalog; price shows "unknown" |
| MBTA V3 | Stops, schedules, predictions, alerts | Walking only; T trips are not guessed |
| National Weather Service | Forecast for the requested hour | Weather component dropped |
| MLB / NHL schedules | Nearby games | Keeps the last good list; dropped if never loaded |
| OpenRouteService | Street-routed walks (non-Google places) | Straight line × 1.3 at 78 m/min, labeled approx. |
| Gemini | Free text → filters; "Why this?" sentence | Rule-based parser; template explanation |
| TikTok (opt-in) | Taste tags | Taste dropped |
| Boston Open Data | 311 requests and licenses near you | "Unavailable", no numbers substituted |
| Tiger Data | Last-train reliability | Nothing shown |

**Grounded explanations.** The Gemini "Why this?" sentence is only accepted if every number in it appears in that place's facts. Otherwise we fall back to the template, which avoids invented figures.

**Source dots.** Green = live. Grey = demo, cached, disabled or unavailable. The sources strip and the details popup both use this rule.

## Product and interface choices

- **One screen, one decision.** Plan a night (vibe, when, spend, how long to get there) → a shortlist of up to 8 cards. Plus a Map view of campuses and the T.
- **Cards show the trip, not just the place.** Line color pill, stops, walk and ride minutes, and the last train back, in the MBTA's own line colors.
- **Score you can open.** The FIT number with "Why this?" for the full breakdown, including parts not used.
- **Saved places stay on the device** (`localStorage`), and their categories feed taste scoring. No account needed.
- **Accessible by default:** popups are labeled dialogs that close with Escape, buttons have labels and pressed states, and the layout fits a 390 px phone width.
- **Look:** the "T-Recs" dinosaur-garden theme, navy and gold, Lilita One headings and Open Sans body text.

## Engineering choices

- **Stack:** React + Vite frontend and a FastAPI (Python 3.12) backend, both on Render. The static site rewrites `/api/*` to the API, so no CORS setup is needed.
- **Resilience:** `request_json` wraps outside API calls with a timeout, one retry (on 429, 5xx, timeouts and connection errors) and a per-source circuit breaker. Public data (MBTA, NWS, Boston Open Data, schedules) also goes through a SQLite TTL cache; Google Places, Gemini and routing are never cached. Tiger reads have their own 3-second timeout and a one-minute skip after a failure.
- **Abuse limits:** 30 requests a minute per visitor and 120 a minute site-wide on endpoints that spend API quota.
- **Validation at the edge:** times must be within the next 24 hours, walk limits 1–120 minutes, free text at most 300 characters, ids in the reliability endpoint are pattern-checked, and all SQL is parameterized.
- **Secrets** live only in `.env` (git-ignored) and Render environment settings, never in the frontend bundle.
- **CI/CD:** every PR runs backend tests, typecheck and build, and a Playwright demo walkthrough. After a merge to `main` passes, CI calls Render deploy hooks for that exact commit.

## Known limits

- Momentum is unavailable in live mode (Google terms), so live rankings use at most five components.
- Walk times for Google places are straight-line estimates (Google terms forbid sending their coordinates to other routers), always labeled approx.
- Reliability covers 12 stations and only trips that have a schedule. During shuttles (like the Red Line Broadway–North Quincy work), affected stations show nothing.
- Events cover Red Sox and Bruins home games only; Ticketmaster is pending approval.
- OpenStreetMap backup places have no ratings or prices, so they rank mostly on reach and weather.

## Where to change things

| To change | Edit |
|---|---|
| Component weights and thresholds | `scoring/weights.yaml` |
| Scoring formulas | `score_venue`, `taste_score` in `backend/app/main.py` |
| Reachability rules | `assess_mbta_round_trip`, `reach_for` in `backend/app/main.py` |
| Reliability stations, threshold, window | `STATIONS`, `MIN_TRAINS`, `WINDOW_H` in `backend/app/reliability.py` |
| Card text | `TransitRow` in `src/main.tsx` |
