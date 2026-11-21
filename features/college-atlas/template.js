export const template = `
<div id="map" aria-label="Interactive Boston campus map"></div>
<section class="panel"><div class="eyebrow">BOUNDLESS BOSTON</div><h1>The city, in perspective.</h1>
<p>Explore the Charles, Boston’s skyline, and the campuses woven through it.</p>
<label for="search">Search campuses</label><input id="search" type="search" placeholder="Try Boston or MIT" autocomplete="off">
<label for="campus">Fly to a university</label><select id="campus"></select>
<div id="matches" role="status"></div>
<div class="buttons"><button id="river" type="button">River view</button><button id="dimension" type="button">2D view</button></div>
<div id="selection" aria-live="polite">Choose one of 19 campuses to explore.</div>
<p>Drag to explore · Scroll to zoom<br>Right-drag to tilt and rotate</p>
<div id="status" role="status">Loading Boston…</div></section>
<div class="note">Real building footprints · Simplified 3D heights · Campus pins mark approximate centers, not boundaries.</div>
`;
