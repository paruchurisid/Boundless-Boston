# 03 — Resilience, caching, and security

## Shared outbound HTTP wrapper

All source adapters call one async HTTP client. Defaults: 4.0 s total request timeout; one retry after a randomized jitter delay uniformly selected from 100–400 ms, only for connect/read timeout, 429, or 5xx; no retry for other 4xx or unsafe non-idempotent requests. Retry sends the same idempotent GET/query. Per-source circuit breaker counts consecutive terminal failures (including exhausted retry); opens at 3, remains open 60 s, then allows one half-open probe. Probe success closes and resets count; failure reopens for 60 s. Concurrent half-open probes are prohibited. Cache lookup precedes network and remains available while open. Do not retry authentication/validation errors.

Failures are typed: `timeout`, `rate_limited`, `upstream_5xx`, `upstream_4xx`, `decode_error`, `circuit_open`, `missing_configuration`. Logs include source, route template, status, latency, cache decision, retry number, and request correlation ID. Never log query strings containing coordinates or user-provided free text; log only normalized request class and a keyed/one-way request identifier.

## SQLite TTL cache

Key: `(source, normalized_params_hash)`, where normalized params are canonical JSON with sorted keys, rounded coordinates (4 decimals for discovery; exact only where endpoint semantics require), normalized time bucket, and relevant query/filter fields. Hash with SHA-256. Store response JSON, `fetched_at`, `expires_at`, schema version, and source metadata. SQLite WAL, bounded DB size (default 250 MB), expired-first eviction; no user profiles, identifiers, locations linked to a person, free text, auth tokens, or request bodies. Query coordinates are operational input and are not persisted in cache keys in recoverable form. Cache stores public third-party responses only after stripping credentials and private headers.

Fresh cache returns `cached` with age. Stale data may be served only under per-source stale-if-error policy; label `cached`, include age and stale flag. In demo mode, fixture fallback status is `demo`, never `cached`. Production with no cache/failure reports unavailable/disabled; it never silently loads fixtures.

## Source TTL and compliance rules

| Source | Fresh TTL / stale-if-error | Rules |
|---|---|---|
| Google Places | No disk cache of Places content. Store `place_id` only if needed; coordinates may be cached only within Google’s stated 30-day exception and are not cached by this app. | `place_id` may be stored indefinitely. Ratings, review counts, price, hours, names, and addresses are fetched for the current response and not persisted. Review-count snapshots are disabled; missing review velocity scores 0 with an explicit reason. Google Places results are not drawn on the Leaflet/OSM map; cards include `Google Maps` attribution and provider attributions. Render Google Maps attribution beside each Places card and display returned third-party provider attributions. Use `translate="no"`; never draw Places points on the Leaflet/OSM map. |
| MBTA | Predictions 30 s; schedules/stops 6 h; alerts 60 s. Keyless mode: aggressive cache (predictions 60 s, schedules/stops 12 h, alerts 2 min) | Optional key is server-side. Cache hard when keyless/rate-limited; state age clearly. Keep service date/timezone semantics. |
| Open-Meteo | 10 min; stale up to 2 h | No key; include attribution/terms link. |
| Boston CKAN | 1 h; neighborhood aggregates stale up to 24 h | At startup call CKAN `package_show` by configured package names, discover datastore resource IDs dynamically, then query `datastore_search`. Never hardcode resource IDs. Support Boston 311 “NEW SYSTEM” plus year-specific schemas by inspecting field names and mapping a versioned alias set; fail section gracefully on unknown schema. Refresh dynamic IDs at startup and periodically (e.g. every 24 h). |
| Ticketmaster | 10 min; stale up to 1 h | API key secret; follow event API display/attribution and rate limits. |
| Yelp Fusion | 24 h cache only if terms allow; stale retention disabled absent compliance review | Do not store/reuse Yelp content beyond permitted policy. Keep Yelp attribution on displayed business data; no review text copied. Cross-check-only by default. |
| Overpass | 24 h minimum request cache; stale up to 7 d | Respect public instance usage policy, identify app, bound area/query, avoid repeated requests. Switch endpoint or disable when policy/limits require. Never scrape for high-volume service. |
| Routing | 30 min; stale up to 6 h | Provider-specific terms govern route retention; never use public OSRM demo server. |
| Gemini | No cache for user free text by default; optionally cache only parsed normalized filters without original text if privacy review approves | Send minimal input; API key server-side; disable and use deterministic regex/templates if unconfigured. |
| Census ACS | 30 d | Public aggregate data only; avoid presenting ecological data as individual attributes. |

TTL values are application defaults; restrictive upstream terms always take precedence and require a config change before production.

## Boston CKAN schema discovery

At startup resolve each configured package through CKAN `package_show`; find resources advertising datastore support and select by configured semantic dataset role plus field/schema fingerprint, not a fixed resource ID. Store resolved IDs in memory with resolution timestamp. On lookup failure, use prior resolved ID only if still confirmed usable, otherwise cache/fixture in demo mode or mark section unavailable. For 311, support current “NEW SYSTEM” package/resource and yearly historical schemas; schema adapter maps request type/category, created date, status, latitude, longitude aliases. Validate expected fields on each discovery; unknown schema produces explicit `schema_unrecognized` health detail rather than silently returning zero. Business license resources use equivalent dynamic discovery.

## Security boundary

Secrets (`GOOGLE_MAPS_API_KEY`, MBTA, Ticketmaster, Yelp, routing, Gemini via `GEMINI_API_KEY`) exist only in backend environment/secret manager; frontend build environment contains only explicitly public variables. `.env` is ignored and never committed. Validate lat `[-90,90]`, lng `[-180,180]`, budget enum exactly `$|$$|$$$`, time between now and now+24 h in UTC conversion, walk integer 1–120, radius bounded 50–5000 m, free text ≤300 chars. Reject NaN/Infinity, malformed encodings, and unknown fields unless contract explicitly allows them. Escape/sanitize rendered text; no HTML from provider is trusted.

Apply per-IP rate limits at BFF: 30 query requests/minute and 60 neighborhood/health requests/minute, configurable; return 429 with `Retry-After`. Trust forwarded IP headers only from configured reverse proxies. CORS allowlist only deployed origins. Structured logging redacts API key patterns, Authorization headers, cookies, coordinates, and free text; run a CI frontend bundle grep for secret-like patterns and fail build on matches. Add dependency pinning/lockfile and security updates. No user account or user-data persistence is in Phase 0 scope.
