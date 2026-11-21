# 02 — Data contracts and scoring

All timestamps are RFC 3339 UTC. JSON numbers are finite; coordinates use WGS84 decimal degrees. Every API response envelope contains `sources_used: SourceUse[]` and `generated_at: string`. Errors use `{error:{code,message,details?},sources_used:[],generated_at}`; validation errors are HTTP 422.

## Unified domain types

```ts
 type SourceId = 'google_places'|'mbta'|'nws'|'boston_ckan'|'ticketmaster'|'yelp'|'overpass'|'routing'|'gemini'|'census_acs';
 type SourceMode = 'live'|'cached'|'demo'|'disabled'|'open-circuit';
 type Attribution = {source: SourceId; text: string; url?: string; required_logo?: string; translate_no?: boolean};
 type SourceRef = {source: SourceId; external_id: string; url?: string};
 type Venue = {
   id: string; name: string; lat: number; lng: number; address: string|null;
   categories: string[]; price_level: 1|2|3|null; rating: number|null;
   review_count: number|null; open_hours: {timezone:string; periods: unknown[]|null; status_at_requested_time:'open'|'closed'|'unknown'; source:SourceId|null}|null;
   source_refs: SourceRef[]; attributions: Attribution[];
   indoor_outdoor: 'indoor'|'outdoor'|'mixed'|'unknown';
   provenance: {field_sources: Record<string,SourceId[]>; observed_at: string; mode: SourceMode};
 };
```

`id` is a stable internal UUID/slug, not an upstream identifier. Null denotes unavailable, never zero. `price_level` maps to `$=1`, `$$=2`, `$$$=3`; unknown price is not eligible under a strict budget filter. Categories are normalized lowercase slugs with display labels held by the client/domain mapping.

## API contracts

`POST /api/query` accepts `{free_text?:string, time:string, budget:'$'|'$$'|'$$$', lat:number, lng:number, max_walk_min:integer, weather_override?:'clear'|'rain'|'cold'}`. `time` must be within the next 24 hours; `max_walk_min` is 1–120. Free text max 300 chars. `GET /api/recommendations` accepts equivalent structured query params, including repeated/encoded free_text only if the implementation supports it; canonical encoding must be documented. Both return:

```json
{"query":{"time":"...","budget":"$$","lat":42.35,"lng":-71.06,"max_walk_min":15},"recommendations":[{"venue":{},"score":{"value":0.72,"components":{"momentum":{"value":0.6,"weight":0.3,"raw":{},"sources":[],"label":"approx."}},"explanation":"..."}}],"sources_used":[],"generated_at":"..."}
```

Recommendation list has 5–8 entries when that many qualify; otherwise it returns all qualifying entries (0–4 included). Zero results use exact empty-state copy: `Nothing open and reachable at that time. Try an earlier hour or a higher budget.` A recommendation score must always contain component values, raw inputs, weights, and sources; never emit a bare score.

`GET /api/neighborhood?lat=&lng=&radius_m=` returns `{center:{lat,lng},radius_m,311:{period_start,period_end,top_categories:[{category,count}]},business_licenses:[{name,issued_at,lat,lng,source_ref}],city_contacts:[{name,service,phone,url,distance_m,source_ref}],sources_used,generated_at}`. Missing sections are `null` with source failure reason metadata, not empty arrays implying verified zero.

`GET /api/sources/health` returns `{sources:[{source,status,checked_at,last_success_at,cache_age_s,mode,detail}],sources_used,generated_at}`. `status` is one of the five states. `mode` describes this deployment (`live-enabled`, `fixtures-enabled`, or `disabled`); status describes the latest usable result.

`SourceUse` is `{source,status:'live'|'cached'|'demo'|'disabled'|'open-circuit',observed_at:string|null,cache_age_s:number|null,attribution:Attribution[]}`. A response can use multiple statuses for one source only if per-record provenance is supplied; otherwise consolidate to the least-fresh applicable status.

## Venue resolution (deduplication)

Normalize names with Unicode NFKC, casefolding, punctuation-to-space, whitespace collapse, and removal of common legal suffixes (`inc`, `llc`, `co`) only for similarity. Compute token-set similarity as the Sørensen-like token-set ratio (intersection/union × 100) and also standard token-sort ratio; use the larger value. Candidate pair matches only if geodesic haversine distance is **≤60 m** and similarity is **≥85**. Google is the primary canonical record when present; otherwise choose the record with most populated fields, stable tie-break source order `overpass`, `yelp`. Merge unique `source_refs` and all required `attributions`; per-field values retain field-level source provenance. Do not merge chain locations beyond threshold.

Ten fixture pair categories required: (1) exact same name/same coordinate duplicate; (2) punctuation/abbreviation duplicate; (3) reordered-word duplicate; (4) Google+Yelp duplicate with Google canonical; (5) Google+OSM duplicate with attribution union; (6) same-block distinct businesses near-miss (different names); (7) adjacent branches same brand >60 m; (8) same coordinate with similarity <85; (9) similar name within 60 m but different suite/business; (10) identical name >60 m. At least categories 1 and 4 are true duplicates with assertive merge; categories 6 and 7 are non-merges. Threshold boundary tests include exactly 60 m/85 and just outside each.

## Hard-filter pipeline

Before scoring: (1) requested-time opening status must be `open`; unknown hours are excluded with reason `hours_unknown`; (2) known price must be ≤ selected budget; unknown price is excluded; (3) walk time must be ≤ max_walk_min; unknown route/walk estimate is excluded unless a documented estimate is available and visibly labeled; (4) trip must satisfy round-trip MBTA-before-last-service or walk fallback per reach rules. Steps (3) and (4) are alternatives: a venue beyond the walk limit stays eligible when an MBTA round trip is confirmed. Each excluded candidate may be returned only in debug/demo diagnostics, never as a ranked result. Eligibility reasons are stable machine codes.

## Transparent scoring

`scoring/weights.yaml` exact shape:

```yaml
version: 1
scale: {min: 0.0, max: 1.0}
weights: {momentum: 0.30, quality: 0.30, reach: 0.20, events: 0.10, weather: 0.10}
quality: {prior_reviews_m: 50, prior_rating_c: candidate_median_rating, rating_max: 5.0}
momentum: {window_days: 30, source_priority: [google_places], snapshot_fallback_label: 'approx.'}
reach: {mbta_round_trip: 1.0, walking_fallback: 0.5, unreachable: 0.0}
events: {radius_m: 804.672, horizon_hours: 3, saturation_count: 3}
weather: {default: 0.5, precipitation_chance_threshold_pct: 50, cold_threshold_f: 40, indoor_adverse: 1.0, outdoor_adverse: 0.0, neutral_type: 0.5}
```

At runtime `candidate_median_rating` is the median of non-null eligible candidate ratings, or 3.0 if none; clamp all normalized components to `[0,1]`. Momentum is review-count delta in the last 30 days normalized as `min(1, max(0, delta)/10)` only where the source contract permits retaining the dated inputs. Google Places content is not persisted by this implementation, so Google review snapshots are disabled; its momentum is 0 with reason `google_review_velocity_not_persisted_for_provider_compliance`. If a future provider explicitly exposes dated velocity, mark it `approx.` and return the timestamped raw inputs. If no permitted velocity exists, momentum is 0 with reason `no_velocity_data`; the component is labeled as missing rather than `approx.`. In demo mode, fixture velocity remains labeled `demo`.

Bayesian quality: `R'=(v/(v+m))*R + (m/(v+m))*C`, `m=50`, `C=median eligible candidate rating`; `quality=R'/5`. If rating/review count unavailable, use component 0.5 with missing-data reason and no invented raw rating. Reach is 1.0 when a live prediction confirms the outbound trip and a same-route scheduled return exists before the last service window (the return is 3+ h out, beyond MBTA's prediction horizon, so it can only be schedule-confirmed); 0.5 when a same-route scheduled pair confirms a return before the last scheduled service window or the venue is reachable by walking fallback; else 0.0. The score's raw method identifies `predicted_round_trip`, `scheduled_round_trip`, or `walking_fallback`; scheduled and walking plans are not presented as live predictions. Events=`min(1,count/3)`. If event provider is unavailable, use 0 and label unknown source (never describe as zero events). Weather starts at 0.5; if precipitation chance ≥50% or temp <40°F, indoor=1, outdoor=0, mixed/unknown=0.5. Weather override changes the effective weather input and must be shown in raw inputs.

Final `score = Σ weight_i × component_i`, with base weights from `scoring/weights.yaml` (.30 momentum, .30 quality, .20 reach, .10 events, .10 weather). **Components with no data (a `missing_reason`) get weight 0 and the remaining weights are rescaled to sum to 1**, so a missing source never caps the score; each component reports `base_weight` and the effective `weight`. This supersedes the per-component "use 0 / 0.5 when missing" defaults above for ranking purposes; those values are still reported but carry no weight. Round only for display (2 decimals); preserve full precision in API. Every component has `{value,weight,raw,sources,method,label?,missing_reason?}`. Explanation text must cite only returned breakdown values.
