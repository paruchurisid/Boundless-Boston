# 01 — System overview

## Purpose and system boundary

Boundless Boston Navigator produces a short list of places that fit a requested outing and can be reached and returned from under the stated walking/transit constraints. Its defining trust rule is that each source is visibly labeled `live`, `cached`, `demo`, `disabled`, or `open-circuit`; a fixture is never represented as live data. All external HTTP traffic passes through one backend resilience wrapper. The browser never calls third-party data APIs with secret credentials.

## High-level architecture

```text
┌────────────────────────────── Browser ───────────────────────────────┐
│ React + Vite + Tailwind + Plasma UI (no map; see doc 04)             │
│ Query form | ranked venue cards | Neighborhood | source health       │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ same-origin JSON API
┌──────────────────────────────▼───────────────────────────────────────┐
│ FastAPI BFF                                                          │
│ validation | query orchestration | hard filters | scoring | payloads │
└──────────────────────────────┬───────────────────────────────────────┘
┌──────────────────────────────▼───────────────────────────────────────┐
│ Resilience middleware                                                │
│ shared HTTP wrapper | timeout/retry | circuit breakers | TTL cache   │
└──────────────┬───────────────────┬────────────────────┬──────────────┘
               │                   │                    │
       ┌───────▼──────┐    ┌───────▼──────┐    ┌────────▼────────┐
       │ Tier 1        │    │ Tier 2       │    │ Tier 3          │
       │ Google Places │    │ Ticketmaster │    │ Census ACS      │
       │ MBTA          │    │ Yelp         │    │ stretch only    │
       │ NWS weather   │    │ Overpass     │    └─────────────────┘
       │ Boston CKAN   │    │ routing/LLM  │
       └───────┬──────┘    └───────┬──────┘
               └──────────────────┬┘
                    ┌─────────────▼─────────────┐
                    │ SQLite disk TTL cache     │
                    │ public third-party data   │
                    ├───────────────────────────┤
                    │ versioned demo fixtures   │
                    └───────────────────────────┘
```

No map tiles are loaded: the OSM map was removed for Google Maps Platform terms (see doc 04).

## Tier gates and delivery rule

**Tier 1 is the demo-critical system.** It comprises Google Places, MBTA V3, National Weather Service, and Boston CKAN. Each adapter must have a working live path when configured, a zero-key fixture path, attribution, normalized contracts, and failure/degradation behavior. “100% green” means all Tier 1 acceptance checks in `05-test-and-demo-plan.md` pass, including each source's no-key fixture scenario and killed-source resilience. Do not start Tier 2 integration until that gate passes.

The project has a hard hour-10 cutover: at hour 10 from implementation start, if Tier 1 is not 100% green, freeze Tier 1 scope and spend all remaining implementation time on Tier 1 stabilization, integration, demo behavior, and tests. Tier 2 must not be touched in that case. If Tier 1 is green by hour 10, Tier 2 may be attempted in the remaining planned window; this does not relax Tier 1 stability. Tier 3 remains stretch scope.

Dependency direction is one-way: UI → BFF contracts → domain services → source adapters → resilience wrapper/cache/fixtures. Adapters return normalized data plus provenance; adapters do not score or make UI decisions. The BFF owns hard filters and scoring.

## Request lifecycle

1. Validate request shape, coordinates, time horizon, budget, and walk limit.
2. Resolve free text deterministically or, when enabled, through the Tier 2 parser; validate parsed filters against the same schema.
3. Fetch candidates/weather/transit/neighborhood/event context concurrently where independent. Every request uses source adapters and the shared wrapper.
4. Normalize candidates, resolve duplicates, retain source references and attributions.
5. Apply hard filters before scoring. Never manufacture eligibility when required data is unavailable: mark the affected dimension unknown and apply the documented fallback or exclude if eligibility cannot be established.
6. Score eligible venues; include all raw inputs, weights, provenance, and approximation labels.
7. Return `sources_used`, UTC generation time, source health/provenance, and results. UI renders source state and attribution adjacent to affected data.

## Graceful-degradation matrix

“Unavailable” means the request continues where a safe fallback exists and the response identifies the fallback. Fixture mode applies only when explicitly configured (development/demo); production does not silently substitute fixtures.

| Source / failure | Timeout or ordinary failure | Missing key | Open circuit | Result behavior |
|---|---|---|---|---|
| Google Places | Do not disk-cache Places content; use demo fixture only in demo mode, otherwise no Google candidates | Same as failure; source `disabled` in production | No Google content cache; fixture only in demo mode; `open-circuit` state exposed | No live candidate discovery. Do not fabricate Google ratings/hours. If no other candidate source is enabled, return empty state. |
| MBTA | Serve cache or fixture; mark reach estimate and age | Keyless mode uses aggressive cache and public V3 endpoints; no key is not itself disabled | Use valid cache/fixture; otherwise reach unknown | A 1.0 reach score requires paired real-time predictions; a validated same-route scheduled round trip or walk fallback is labeled separately at 0.5. If neither can be established, exclude the venue. |
| National Weather Service | Cache or fixture; otherwise weather component `0.5`, labeled default | No key needed | Cache/fixture or neutral `0.5` | Weather does not block recommendations; expose unavailable source. |
| Boston CKAN | Cache or fixture for neighborhood; otherwise neighborhood section unavailable | No key needed | Cache/fixture or section unavailable | Core venue recommendations remain available; no invented 311/license/contact summary. |
| Ticketmaster | Cache/fixture or events count 0 with source unavailable (never claim verified zero if fetch failed) | Disabled; event count unknown and events component neutral 0 unless product config explicitly defines otherwise | Same | Tier 2 only; recommendation continues, events contribution uses documented missing-data policy. |
| Yelp | Cache where policy allows; otherwise omit cross-check | Disabled; omit | Omit | Never block Google candidate; no Yelp content shown without compliance metadata. |
| Overpass | Cache/fixture, else omit OSM candidates | No key normally; configuration/policy may disable | Omit | Never treat missing data as proof that a place is closed. |
| Routing provider | Cache/fixture, else use documented conservative straight-line walk estimate only if UI marks it estimated; otherwise exclude unknown walk eligibility | Disabled | Same | Never present estimate as routed time. Tier 2. |
| Gemini parser/explainer | Deterministic parser/template fallback | Disabled | Fallback | No unsupported claims; explanations derive only from response breakdown. |
| Census ACS | Cache or omit | Disabled | Omit | Tier 3 optional context only; never changes core eligibility. |

Common wrapper states and cache freshness semantics are specified in `03-resilience-caching-and-security.md`. A stale record is not silently presented as live. A fixture record carries `mode=demo` and a visible demo badge.
