# Source catalog

This catalog defines intended source use. Current credentials, quotas, retention, attribution wording, and API versions must be confirmed against each provider's current terms before production. Adapters expose source mode and observed time so cached and fixture data cannot masquerade as live.

| Source | Tier / purpose | Key | Cache / resilience | Attribution and display | Demo fixture |
|---|---|---|---|---|---|
| Google Places API (New) | 1; venue discovery/details, rating/count, price, hours, location, map URI | Required for live; server only | No disk cache for Places content; place_id may be retained indefinitely; coordinates only under provider exception, not cached here | Show Google Maps attribution with card content and render returned third-party attributions. Mark text `translate="no"`. Do not persist Places content or draw Places points on the OSM map; place IDs may be retained, and coordinate retention is not used by this app. | Boston venues with explicit DEMO provenance and synthetic IDs. |
| MBTA V3 | 1; stops, predictions, schedules/last service, alerts | Optional | Predictions 30s (60s keyless); schedules/stops 6h (12h keyless); alerts 60s (2m keyless) | Link/credit MBTA; clearly timestamp transit status and distinguish prediction from schedule. | Deterministic stops, trips, last-service and alert scenarios. |
| National Weather Service (api.weather.gov) | 1; hourly temperature and precipitation chance (US only) | None; identifying User-Agent required | 10m, stale ≤2h | Credit the National Weather Service and link weather.gov. | Clear/rain/cold weather variants. |
| data.boston.gov CKAN | 1; 311 last 90 days, business licenses, city contacts | None | Dynamic resource resolution; 1h; aggregate stale ≤24h | Credit City of Boston and link dataset. | 311 category, license, contacts fixtures with date window. |
| Sports schedules: MLB Stats API (Red Sox) and NHL web API (Bruins) | 2; big home games at Fenway / TD Garden as the events signal | None | 6 h in memory; 5 min backoff on failure | Credit "MLB Stats API (© MLB Advanced Media)" and NHL. MLB's copyright notice limits use to individual, non-commercial purposes; the NHL API is undocumented and unofficial. Review both before a commercial launch. | Demo mode has no event fixtures (events "not used"). |
| Ticketmaster Discovery | 2; events within 0.5 mi, next 3h | Required | 10m, stale ≤1h | Required event/provider attribution and links; follow display terms. | Nearby event counts and examples labeled DEMO. |
| Yelp Fusion | 2; cross-check/dedupe only by default | Required | 24h only if terms permit; no stale retention without compliance review | Yelp attribution/logo and display rules wherever content shown; avoid review text; honor content-use limitations. | Minimal IDs/names for dedupe fixtures, not copied user content. |
| OSM Overpass (backup only; read from a bundled snapshot, not queried per request) | 2; venue fallback when Google Places is unavailable, with `opening_hours` | Usually none | At least 24h request cache, stale ≤7d; strict bounded usage | Credit OpenStreetMap contributors; display OSM attribution with map/data. | Synthetic OSM venue/opening-hours cases. |
| Routing provider | 2; walking minutes, Mapbox Directions or OpenRouteService | Required depending provider | 30m, stale ≤6h subject to terms | Provider-required route attribution. Never use public OSRM demo server. | Fixed route times and estimated fallback examples. |
| Google Gemini API (Flash-class model) | 2; free text to structured filters and grounded one-sentence “why” | Required | No raw prompt cache by default | No user-facing attribution required unless terms change; disclose parsing only if product requires. | Parser fixtures; deterministic regex/template fallback. Requested model name must be verified as available before implementation. |
| US Census ACS 5-year | 3; neighborhood demographic context | None/key per current API requirements | 30d | Cite Census/ACS and year; clearly contextual, not individual-level. | Small aggregate fixtures clearly labeled demo. |

## Compliance notes

Google Maps Platform ToS 3.2.3(e) and Service Specific Terms 14.2 bar using Places content with or near a non-Google map, so the app shows no map. ToS 3.2.3(a)/(c) bar exporting Places coordinates for use outside the Services, so Google venues are never sent to OpenRouteService. Google place data must preserve Google attribution wherever displayed; this UI uses text attribution with each card, and suppresses Places-derived points on the OSM map. Apply `translate="no"` as specified by current Places terms. Do not persist Places content, review snapshots, or rating-derived state. `place_id` is treated as indefinitely retainable; other Places fields are restricted and must follow current retention rules. Yelp data is subject to strict display/storage terms: keep Yelp as cross-check unless a specific UI use is reviewed, include logo/attribution when shown, and do not copy review text. OSM queries must be bounded, cached, identified, and rate-limited; do not use Overpass as a bulk extraction service. Boston CKAN resource identifiers are resolved dynamically at startup via `package_show`, with no hardcoded resource IDs. Default neighborhood license source is Boston Active Food Establishment Licenses, with the package configurable to a compatible City license dataset. All compliance defaults yield to more restrictive current provider terms.

## Excluded sources

| Source | Reason excluded |
|---|---|
| Snapchat / Snap Map | No suitable supported public discovery API for this product; privacy and reliability concerns. |
| Reddit | Unstructured, weak venue-hours/reachability signal; API and content terms do not justify ingestion. |
| Eventbrite public search | Public search scraping is not an approved integration path; Ticketmaster is selected for scoped event API. |
| TikTok | No dependable, permitted venue/event data interface for this use. |
| Instagram | Access and content reuse restrictions; not a reliable structured venue availability source. |
| Open-Meteo | Replaced by NWS: its free tier returned HTTP 429 to Render's shared outbound IPs on every request. A paid Open-Meteo key would also work. |
| Google Trends | Search interest is not venue-level current availability or trip feasibility; not needed for MVP scoring. |
