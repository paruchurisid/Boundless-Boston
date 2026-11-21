import { campuses } from './campuses.js';
import { template } from './template.js';

/** Mount into an empty host. Call destroy when removing the tab. */
export function mountCollegeAtlas(host, { maplibre, onCampusChange } = {}) {
  if (!maplibre) throw new Error('Pass the MapLibre GL JS module as maplibre');
  const root = host.shadowRoot || host.attachShadow({mode:'open'});
  if (root.childNodes.length) throw new Error('Atlas host is already mounted');
  const maplibregl = maplibre;
  root.innerHTML = template;
  for (const href of [new URL('./atlas.css', import.meta.url).href, 'https://unpkg.com/maplibre-gl@5.6.1/dist/maplibre-gl.css']) {
    const link = document.createElement('link'); link.rel='stylesheet'; link.href=href; root.prepend(link);
  }

const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
const initial={center:[-71.090,42.3535],zoom:14.5,pitch:62,bearing:-32};
const status=root.getElementById('status'),select=root.getElementById('campus');
let map;
try { map=new maplibregl.Map({container:root.getElementById('map'),style:'https://tiles.openfreemap.org/styles/liberty',...initial,maxPitch:75,canvasContextAttributes:{antialias:true}}); } catch {
  status.textContent='Interactive map unavailable. You can still search and select all 19 campuses below.';
  root.getElementById('dimension').disabled=true;
}

map?.addControl(new maplibregl.NavigationControl({visualizePitch:true}),'top-right');map?.addControl(new maplibregl.ScaleControl(),'bottom-right');
function fly(i){const c=campuses[i];if(!c) return;root.getElementById('search').value='';filterCampuses();root.getElementById('selection').textContent=c[0]+' · '+c[1].toFixed(4)+'° N, '+Math.abs(c[2]).toFixed(4)+'° W';select.value=String(i);onCampusChange?.({name:c[0],lat:c[1],lng:c[2]});map?.flyTo({center:[c[2],c[1]],zoom:16,pitch:62,bearing:-25,duration:reduced?0:1600});root.getElementById('dimension').textContent='2D view';}
function filterCampuses(){
 const query=root.getElementById('search').value.trim().toLowerCase();
 const previous=select.value;
 select.replaceChildren(new Option('Charles River overview',''));
 const visible=campuses.map((c,i)=>({c,i})).filter(({c})=>c[0].toLowerCase().includes(query));
 visible.forEach(({c,i})=>select.add(new Option(c[0],String(i))));
 if([...select.options].some(o=>o.value===previous)) select.value=previous;
 root.getElementById('matches').textContent=visible.length?visible.length+' campuses':'No campuses found. Try another name.';
}
root.getElementById('search').oninput=filterCampuses;
filterCampuses();
campuses.forEach((c,i)=>{if(!map)return;const el=document.createElement('button');el.className='campus';el.textContent=c[0];el.setAttribute('aria-label','Explore '+c[0]);el.onclick=()=>fly(i);new maplibregl.Marker({element:el,anchor:'bottom'}).setLngLat([c[2],c[1]]).addTo(map)});
select.onchange=()=>select.value===''?overview():fly(Number(select.value));
function overview(){root.getElementById('search').value='';filterCampuses();select.value='';root.getElementById('selection').textContent='Choose one of 19 campuses to explore.';onCampusChange?.(null);map?.flyTo({...initial,duration:reduced?0:1600});root.getElementById('dimension').textContent='2D view'}
root.getElementById('river').onclick=overview;
root.getElementById('dimension').onclick=e=>{const flat=map.getPitch()>10;map.easeTo({pitch:flat?0:62,bearing:flat?0:-32,duration:reduced?0:650});e.target.textContent=flat?'3D view':'2D view'};
map?.on('load',()=>{const style=map.getStyle();const buildings=style.layers.find(l=>l['source-layer']==='building');if(buildings){for(const l of style.layers.filter(l=>l.type==='fill-extrusion'))map.setLayoutProperty(l.id,'visibility','none');const before=style.layers.find(l=>l.type==='symbol')?.id;map.addLayer({id:'boston-buildings-3d',source:buildings.source,'source-layer':'building',type:'fill-extrusion',minzoom:13,paint:{'fill-extrusion-color':['interpolate',['linear'],['coalesce',['get','render_height'],12],0,'#d3dedb',30,'#9eb7b1',100,'#688d87',220,'#3f706a'],'fill-extrusion-height':['coalesce',['get','render_height'],12],'fill-extrusion-base':['coalesce',['get','render_min_height'],0],'fill-extrusion-opacity':.94}},before);status.textContent=campuses.length+' campuses · 3D buildings ready';}else status.textContent='Map loaded; building layer unavailable';});
map?.on('error',e=>{status.textContent='Some map data could not load. Check your internet connection.'});

  const observer = new ResizeObserver(() => map?.resize());
  observer.observe(host);
  let destroyed = false;
  return {
    map,
    resize: () => map?.resize(),
    flyToCampus: (index) => {
      if (!Number.isInteger(index) || index < 0 || index >= campuses.length) throw new RangeError('Unknown campus index');
      fly(index);
    },
    overview,
    destroy() {
      if (destroyed) return;
      destroyed = true; observer.disconnect(); map?.remove(); root.replaceChildren();
    }
  };
}
