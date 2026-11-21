# College atlas

Portable Boston map for embedding in a teammate's tab layout. All feature files
are contained in this directory. No router, app shell, backend, Neon credentials,
global stylesheet, or existing UI changes are required.

## Included

- Real OSM building footprints with simplified 3D extrusions.
- Charles River overview, pan/zoom/rotate, scale and navigation controls.
- Nineteen campus center pins and campus fly-to menu.
- 2D/3D toggle, responsive controls, reduced-motion support and attribution.
- Shadow DOM styling isolation, automatic container resizing and explicit cleanup.

Campus pins are approximate centers, not property boundaries. Building coverage
and heights depend on OSM/OpenMapTiles; this is not a complete surveyed city model.
No venue catalog or Google Places data is used by this feature.

## React integration

Install `maplibre-gl@5.6.1` using the target branch's package manager, then:

```jsx
import maplibre from 'maplibre-gl';
import { CollegeAtlas } from './features/college-atlas/CollegeAtlas.jsx';

<section style={{ height: '75vh', minHeight: 420 }}>
  <CollegeAtlas maplibre={maplibre} onCampusChange={campus => console.log(campus)} />
</section>
```

Copy the feature directory into the target source tree if its bundler only accepts
source imports from there. Vite resolves the local CSS URL in `mount.js`; other
bundlers should preserve `atlas.css` alongside that module. React unmount cleans
up WebGL and observers, including React StrictMode remounts. A hidden tab can remain
mounted; ResizeObserver adjusts the canvas when the container becomes visible.

## Framework-independent integration

```js
import { mountCollegeAtlas } from './features/college-atlas/mount.js';
const atlas = mountCollegeAtlas(hostElement, { maplibre });
atlas.flyToCampus(1); // MIT; indices follow exported campuses.js
atlas.overview();
atlas.resize();
atlas.destroy(); // call when removing the host
```

Use an empty host with a defined height (minimum 420px). Each instance has its own
shadow root, IDs, controls, map and observer. The returned `map` is available for
host-specific extensions. `onCampusChange` receives `{ name, lat, lng }` on campus
selection. The host owns tab selection, layout and navigation.

## Preview

From the repository root:

```sh
python -m http.server 8768 --directory features/college-atlas
```

Open http://localhost:8768. The demo imports pinned MapLibre from esm.sh; the host
application should use its installed module instead. MapLibre CSS is loaded from
unpkg.com inside the shadow root. For deployments without CDN access, change that
stylesheet URL in `mount.js` to a hosted copy of the same version.

Internet access and WebGL are required. Allow OpenFreeMap tiles, its style resources,
MapLibre workers (`blob:`), and the CSS CDN in the host CSP. Keep the map attribution.

## App integration

Open College Atlas in the navigation or visit /#atlas. The app lazy-loads the installed MapLibre module and keeps venue results on the planner view. Campus search and selection remain available when WebGL cannot initialize. Returning to Plan unmounts the map and frees its observers and WebGL resources.

Campus callbacks also receive null when River view clears the selection.

Validation: pnpm typecheck, pnpm build, and pnpm e2e. The Atlas browser tests cover fallback, search, selection, responsive layout and remount cleanup with WebGL disabled, plus map initialization and perspective controls with WebGL enabled and a deterministic style fixture. Live tile availability is not asserted.
