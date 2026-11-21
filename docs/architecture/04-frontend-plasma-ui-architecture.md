# 04 — Frontend and Plasma UI architecture

## Stack and layout

React + Vite + TypeScript, Tailwind, and `@cruxgarden/plasma-ui`. **No map is shown.** Google Maps Platform terms bar using Places content "with or near a non-Google Map" (ToS 3.2.3(e); Service Specific Terms 14.2), so the earlier Leaflet/OSM map was removed. If a map returns, it must be a Google Map, or Places must move to Places UI Kit (SST 15.1). Google Places results stay in attributed venue cards. Mobile-first, responsive two-column desktop layout: fixed plain-CSS source-health strip; query form/header; results column with one scrollable Plasma panel containing semantic HTML venue cards; side column with the neighborhood panel; source details/demo controls. On narrow screens, form → results → neighborhood. All sources, attributions, approximation labels, and score details remain reachable at mobile widths.

## State ownership

URL/query state holds shareable non-secret structured filters (time, budget, rounded center, walk limit); transient free text is not placed in URL. React Query (or equivalent) owns API request/cache state, keyed by canonical query. Local component state owns open accordion/modal and weather override. Source health is polled every 30 s while page visible. Query submit aborts superseded requests. A response's `generated_at` and `sources_used` are rendered as received. Do not infer live status from a successful HTTP response.

## Plasma surface budget

One root `<PlasmaProvider maxSurfaces={16}>` at app shell. `maxSurfaces` is a fixed literal/config for provider lifetime and never changes per frame or from animation state. Surface creation is capped at 16; at saturation, lower-priority decorative surfaces fall back to CSS and do not mount additional Plasma surfaces.

| Surface group | Max surfaces | Priority |
|---|---:|---|
| Header/search field backing | 2 | 1 |
| Query controls / fused segmented controls | 3 | 1 |
| Results panel | 1 | 1 |
| Map framing / filter panel | 2 | 2 |
| Neighborhood panel | 1 | 2 |
| Modal source details / demo controls (secondary provider only while open) | 3 | 2 |
| Toast/status accents | 2 | 3 |
| Reserved/contingency | 2 | 4 |
| **Total ceiling** | **16** | |

Modal is rendered in a portal over a scrim and mounts a secondary `<PlasmaProvider ground="clear" maxSurfaces={3}>` only while open; it is included in the global ceiling. Modal content becomes interactive only after `onFormed` or `data-plasma-forming` indicates formed state, with accessible pending announcement. Closing unmounts the secondary provider.

## Spatial and CSS constraints

Independent `<Plasma>` panels have bounding boxes separated by more than configured `blend` distance. Fused segmented controls use `<PlasmaTabs>` / `<PlasmaTabList>` flush with no gap. The venue list is plain semantic HTML cards inside exactly one scrollable `<Plasma>` panel; never put nested `<Plasma>` surfaces inside a scrollable parent. Leaflet map, inputs, buttons, and `<PlasmaSlider>` use `data-plasma-nodrag` where needed. Do not set CSS `translate`, `scale`, or `transform` on a `<Plasma>` node or its layout wrapper; use layout primitives on non-Plasma siblings. Verify library-specific prop/API names against the installed package before implementation.

## Interaction and moods

Weather state controls Plasma mood: clear night uses the calm clear mood; precipitation or cold toggles to the weather mood and calls `pulse()` through `usePlasmaRuntime()` once on meaningful transition, not every render. Respect `prefers-reduced-motion`: disable pulsing and continuous motion, use static/low-motion preset. `freezeOnScroll` on scroll-heavy panels. Inputs and Leaflet interactions must remain responsive and not be captured as drag gestures.

## Mobile and accessibility

Touch/low-GPU devices use CSS frosted fallback, reduced shader quality/pixel budget, and `freezeOnScroll`; no function may depend on WebGL. Detect capability conservatively and preserve content if context creation fails. Maintain WCAG AA contrast, keyboard navigation, visible focus, reduced-motion handling, semantic headings/lists, accessible score breakdown, map list alternative, and non-color-only source state icons/text. Source-health bar remains fixed plain CSS over scrolling content, with safe-area padding.
