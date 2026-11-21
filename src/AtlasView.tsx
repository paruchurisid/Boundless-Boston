import maplibre from 'maplibre-gl';
import { CollegeAtlas } from '../features/college-atlas/CollegeAtlas.jsx';
export default function AtlasView() {
  return <section aria-label="College Atlas" className="atlas-view">
    <div className="section-head"><div><span className="section-kicker">19 CAMPUSES · GREATER BOSTON</span><h1>College Atlas</h1><p>Find your campus. Get to know the city around it.</p></div></div>
    <CollegeAtlas maplibre={maplibre}/>
  </section>;
}
