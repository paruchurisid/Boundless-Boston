import { lazy, Suspense, StrictMode, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowDownRight, ArrowRight, ArrowUpRight, Bookmark, ChevronDown, ChevronRight, CloudRain, Compass, Crosshair, Footprints, Heart, MapPin, Moon, Music2, SlidersHorizontal, Sparkles, TrainFront, Utensils, X } from 'lucide-react';
import type React from 'react';
import '@fontsource/lilita-one/latin-400.css';
import '@fontsource/open-sans/latin-400.css';
import '@fontsource/open-sans/latin-600.css';
import '@fontsource/open-sans/latin-700.css';
import '@fontsource/open-sans/latin-800.css';
import { Plasma, PlasmaProvider } from '@cruxgarden/plasma-ui';
import './style.css';
const AtlasView = lazy(() => import('./AtlasView'));


type Venue={id:string;name:string;lat:number;lng:number;address:string|null;categories:string[];price_level:number|null;rating:number|null;review_count:number|null;walk_min:number;walk_estimate?:{label:string|null};indoor_outdoor:string;attributions:{source:string;text:string;url?:string;required_logo?:string;translate_no?:boolean}[];source_refs?:{source:string;external_id:string}[]};
type Line={id:string;name:string;color:string;mode:string};
type Leg={route?:string;line?:Line;from_stop?:string;to_stop?:string;depart_at?:string;arrive_at?:string;transfer?:{at:string;line:Line}};
type Rec={venue:Venue;reachability:{method:string;label?:string;outbound?:Leg|null;return?:Leg|null;last_return?:(Leg&{last_of_night?:boolean;reliability?:{avg_delay_min:number;trains:number}|null})|null;total_min?:number|null;walk_to_stop_min?:number;walk_from_stop_min?:number};score:{value:number;components:Record<string,{value:number;weight:number;base_weight?:number;label?:string;missing_reason?:string|null;raw:Record<string,unknown>;sources:string[]}>};explanation:string;reach_explanation?:string;explain_facts?:Record<string,unknown>};
type Result={recommendations:Rec[];sources_used:{source:string;status:string}[];generated_at:string;empty_message:string|null;query:{parsed_filters?:Record<string,unknown>;preference_tags?:string[]};weather:{temperature_f:number|null;precipitation_chance_pct:number|null;forecast_for?:string;override?:string}};
type Neighborhood={center:{lat:number;lng:number};radius_m:number;311:{top_categories:{category:string;count:number}[];period_start:string;period_end:string}|null;business_licenses:{name:string;issued_at:string;address?:string;distance_m?:number}[]|null;business_licenses_source?:string|null;city_contacts:{name:string;service:string;phone:string;url:string}[]|null};
type SavedPlace={place_id:string;name:string;categories:string[];address:string|null;price_level:number|null;saved_at:string};
type PlaceMention={name:string;snippet?:string;source?:string;label?:string};

const SAVED_KEY='boundless.savedPlaces.v1';
const center:[number,number]=[42.355,-71.062];
const clock=(iso?:string)=>iso?new Date(iso).toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit',timeZone:'America/New_York'}):'';
const rideMin=(leg:Leg)=>leg.depart_at&&leg.arrive_at?Math.max(1,Math.round((Date.parse(leg.arrive_at)-Date.parse(leg.depart_at))/60000)):null;
const normName=(s:string)=>s.toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
const namesOverlap=(a:string,b:string)=>{const na=normName(a),nb=normName(b);return !!na&&!!nb&&(na===nb||na.includes(nb)||nb.includes(na));};
// Flat-vector art for the dinosaur garden (own artwork). Colors match style.css.
const C={night:'#13213f',navy:'#1d3461',cream:'#fdf3dc',gold:'#e8be55',leaf:'#3f9a5c',leaf2:'#24704a',leaf3:'#1a5540',dino:'#7cc576',dinoDark:'#56a554',belly:'#e3f4d6',blush:'#f6a59c',lava:'#f08a3c',earth:'#6e4631'};
function Trolley({color='#00843D',size=56}:{color?:string;size?:number}){
 return <svg className="doodle" width={size} height={size*60/64} viewBox="0 0 64 60" aria-hidden="true">
  <path d="M24 9 L32 2 L40 9" fill="none" stroke={C.night} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
  <rect x="9" y="9" width="46" height="38" rx="10" fill={C.cream}/>
  <rect x="9" y="31" width="46" height="8" fill={color}/>
  <rect x="15" y="15" width="14" height="11" rx="3.5" fill={C.night}/><rect x="35" y="15" width="14" height="11" rx="3.5" fill={C.night}/>
  <circle cx="16" cy="35" r="2" fill="#fff3b0"/><circle cx="48" cy="35" r="2" fill="#fff3b0"/>
  <circle cx="20" cy="51" r="5" fill={C.night}/><circle cx="44" cy="51" r="5" fill={C.night}/>
  <circle cx="20" cy="51" r="1.8" fill={C.gold}/><circle cx="44" cy="51" r="1.8" fill={C.gold}/>
 </svg>;
}
const Track=({x,y,r=0,o=1}:{x:number;y:number;r?:number;o?:number})=><g transform={`translate(${x} ${y}) rotate(${r})`} opacity={o}><ellipse cx="0" cy="-11" rx="3" ry="7.5"/><ellipse cx="0" cy="-11" rx="3" ry="7.5" transform="rotate(-38)"/><ellipse cx="0" cy="-11" rx="3" ry="7.5" transform="rotate(38)"/><ellipse cx="0" cy="1" rx="5.5" ry="5"/></g>;
function Steps(){
 return <svg className="doodle" width="46" height="46" viewBox="0 0 46 46" aria-hidden="true"><g fill={C.cream}><Track x={14} y={36} r={-10}/><Track x={32} y={20} r={-10} o={.65}/></g></svg>;
}
// The T-Recs mascot, flat style: same round silhouette, shading instead of ink outlines.
function Dino({size=60,wave=false}:{size?:number;wave?:boolean}){
 return <svg className="doodle dino" width={size} height={size*96/112} viewBox="0 0 112 96" aria-hidden="true"><DinoShapes wave={wave}/></svg>;
}
const DINO_BODY="M6 72 C20 68 31 61 40 57 C43 41 50 25 64 19 C78 12 101 14 106 29 C110 39 104 47 92 47 C85 48 79 50 77 56 C81 66 79 76 71 82 L71 89 Q71 93 67 93 L61 93 Q57 93 57 89 L57 86 Q52 88 47 86 L47 89 Q47 93 43 93 L37 93 Q33 93 33 89 L33 81 C24 80 14 78 6 72 Z";
function DinoShapes({wave=false}:{wave?:boolean}){
 return <g>
  <circle cx="35" cy="54" r="6.5" fill={C.gold}/><circle cx="39" cy="42" r="6.5" fill={C.gold}/><circle cx="46" cy="31" r="6.5" fill={C.gold}/><circle cx="55" cy="22.5" r="6" fill={C.gold}/>
  <path d={DINO_BODY} fill={C.dino}/>
  <path d="M33 81 L33 89 Q33 93 37 93 L43 93 Q47 93 47 89 L47 86 Q40 85 33 81 Z" fill={C.dinoDark}/>
  <path d="M6 72 C14 78 24 80 33 81 L34 76 C24 76 15 75 6 72 Z" fill={C.dinoDark} opacity=".7"/>
  <path d="M57 64 C62 58 72 60 72 70 C72 78 64 82 58 79 C53 76 53 69 57 64 Z" fill={C.belly}/>
  {wave?<path d="M77 59 C80 53 83 50 87 49" fill="none" stroke={C.dinoDark} strokeWidth="4.5" strokeLinecap="round"/>:<path d="M77 60 C82 60 86 62 86 66" fill="none" stroke={C.dinoDark} strokeWidth="4.5" strokeLinecap="round"/>}
  <circle cx="87" cy="29" r="5.4" fill={C.night}/><circle cx="88.8" cy="27" r="1.9" fill="#fff"/><circle cx="85.6" cy="31.2" r="0.9" fill="#fff"/>
  <ellipse cx="80" cy="38.5" rx="4.2" ry="2.7" fill={C.blush}/>
  <path d="M92 38 Q95 41 98 38 Q101 41 104 37" fill="none" stroke={C.night} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/>
  <circle cx="101" cy="25" r="1.1" fill={C.night}/>
 </g>;
}
// Bumpy jungle canopy line, deterministic so it renders the same every time.
const canopy=(y:number,r:number,seed:number)=>{let d=`M0 ${y}`;let x=0,i=0;while(x<1240){const w=r*(0.75+((i*37+seed)%8)/10);const h=r*(0.55+((i*13+seed)%6)/10);d+=` q${(w/2).toFixed(1)} ${(-h).toFixed(1)} ${w.toFixed(1)} 0`;x+=w;i++}return d+' V600 H0 Z'};
function Leaf({x,y,s=1,r=0,fill}:{x:number;y:number;s?:number;r?:number;fill:string}){
 return <g transform={`translate(${x} ${y}) rotate(${r}) scale(${s})`}><path d="M0 0 C20 -70 110 -90 150 -20 C120 -30 105 -5 85 -12 C80 5 60 8 50 -2 C40 15 15 15 0 0 Z" fill={fill}/><path d="M0 0 C40 -30 90 -40 140 -22" fill="none" stroke={C.leaf3} strokeWidth="3" opacity=".5"/></g>;
}
function Palm({x,y,s=1,fill}:{x:number;y:number;s?:number;fill:string}){
 return <g transform={`translate(${x} ${y}) scale(${s})`} fill={fill}><path d="M-3 0 C-1 -40 2 -70 6 -96 l6 1 C9 -70 6 -40 5 0 Z"/><path d="M8 -96 C-10 -110 -40 -104 -56 -86 C-36 -96 -16 -96 8 -94 Z M8 -96 C26 -114 56 -108 70 -88 C50 -98 30 -98 8 -94 Z M8 -97 C0 -120 -22 -130 -40 -124 C-20 -116 -6 -108 6 -94 Z M8 -97 C18 -122 40 -128 56 -120 C36 -114 22 -106 10 -94 Z"/></g>;
}
function GardenScene(){
 return <svg className="garden" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMax slice" role="img" aria-label="A little dinosaur riding a Green Line trolley through a jungle garden, with the Boston skyline at dusk">
  <defs>
   <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#0f1b38"/><stop offset=".42" stopColor="#2a3d6c"/><stop offset=".64" stopColor="#b9705e"/><stop offset=".78" stopColor="#f3a865"/><stop offset="1" stopColor="#ffd79a"/></linearGradient>
   <radialGradient id="glow" cx=".5" cy=".5" r=".5"><stop offset="0" stopColor="#fff4d1" stopOpacity=".95"/><stop offset=".5" stopColor="#ffd08a" stopOpacity=".45"/><stop offset="1" stopColor="#ffd08a" stopOpacity="0"/></radialGradient>
  </defs>
  <rect width="1200" height="600" fill="url(#sky)"/>
  <ellipse cx="600" cy="390" rx="460" ry="190" fill="url(#glow)"/>
  <g fill={C.cream}>{[[90,150,2],[230,60,1.6],[330,170,2.2],[470,40,1.5],[700,90,1.8],[860,40,2.2],[980,150,1.6],[1110,70,2],[560,150,1.3],[1060,220,1.4]].map(([x,y,r],i)=><circle key={i} cx={x} cy={y} r={r} opacity=".85"/>)}
   <path d="M180 120 l3 9 l9 3 l-9 3 l-3 9 l-3 -9 l-9 -3 l9 -3 z M820 170 l2.5 7 l7 2.5 l-7 2.5 l-2.5 7 l-2.5 -7 l-7 -2.5 l7 -2.5 z" opacity=".9"/>
   <path d="M318 52 a40 40 0 1 0 50 60 a33 33 0 1 1 -50 -60 z"/>
  </g>
  <g stroke={C.cream} strokeLinecap="round" opacity=".75"><path d="M1010 70 L900 118" strokeWidth="3"/><path d="M990 96 L930 122" strokeWidth="1.6"/></g>
  <path d="M300 372 V330 h26 v-14 h14 v14 h18 V272 l14 -5 v105 h12 V300 h30 v-8 h10 v8 h12 v72 h16 V318 q22 -30 44 0 v54 h14 V256 h28 V372 h14 V312 h20 v-10 h8 v10 h16 V372 h20 V292 l18 -8 l18 8 V372 h16 V326 h30 V372 Z" fill="#3b3f6e" opacity=".92"/>
  <path d="M880 372 L975 236 h36 L1110 372 Z" fill="#5e4440"/><path d="M975 236 h36 l-6 12 q-12 6 -24 0 z" fill={C.lava}/>
  <g fill="#8a7f96" opacity=".55"><circle cx="993" cy="214" r="14"/><circle cx="1012" cy="196" r="11"/><circle cx="1028" cy="176" r="8"/></g>
  <path d={canopy(372,70,3)} fill="#2d6a68"/>
  <Palm x={140} y={378} s={1.1} fill="#21524f"/><Palm x={760} y={372} s={0.9} fill="#21524f"/><Palm x={1080} y={380} s={1.2} fill="#21524f"/>
  <path d={canopy(420,58,11)} fill="#245a4c"/>
  <rect x="0" y="456" width="1200" height="34" fill="#2b8a8a" opacity=".85"/>
  <path d="M120 470 h70 M420 478 h50 M760 468 h90 M1010 476 h60" stroke="#8fd3cf" strokeWidth="3" strokeLinecap="round" opacity=".6"/>
  <path d="M0 452 H1200" stroke="#5a4232" strokeWidth="5"/>
  <g stroke="#5a4232" strokeWidth="5">{Array.from({length:40},(_,i)=><path key={i} d={`M${i*31+8} 446 v14`}/>)}</g>
  <path d="M0 444 H1200" stroke="#7a5a44" strokeWidth="4"/>
  <g transform="translate(540 362)"><svg width="96" height="90" viewBox="0 0 64 60" overflow="visible"><rect x="9" y="9" width="46" height="38" rx="10" fill={C.cream}/><rect x="9" y="31" width="46" height="8" fill="#00843D"/><rect x="14" y="15" width="10" height="11" rx="3" fill={C.night}/><rect x="27" y="15" width="10" height="11" rx="3" fill={C.night}/><rect x="40" y="15" width="10" height="11" rx="3" fill={C.night}/><circle cx="20" cy="51" r="5" fill={C.night}/><circle cx="44" cy="51" r="5" fill={C.night}/><circle cx="20" cy="51" r="1.8" fill={C.gold}/><circle cx="44" cy="51" r="1.8" fill={C.gold}/></svg></g>
  <svg x="540" y="291" width="100" height="86" viewBox="0 0 112 96" overflow="visible"><DinoShapes wave/></svg>
  <path d={canopy(520,64,21)} fill="#1c4a3c"/>
  <Leaf x={-40} y={600} s={1.5} r={-48} fill={C.leaf}/><Leaf x={60} y={610} s={1.1} r={-70} fill={C.leaf2}/><Leaf x={250} y={612} s={0.9} r={-35} fill={C.leaf}/>
  <Leaf x={1240} y={600} s={1.5} r={-132} fill={C.leaf}/><Leaf x={1150} y={612} s={1.1} r={-110} fill={C.leaf2}/><Leaf x={960} y={615} s={0.85} r={-145} fill={C.leaf}/>
  <g fill="#e9824f"><circle cx="330" cy="548" r="6"/><circle cx="344" cy="540" r="5"/><circle cx="352" cy="552" r="5"/><circle cx="880" cy="552" r="6"/><circle cx="894" cy="544" r="5"/></g>
 </svg>;
}
function Bones(){
 return <div className="bones" aria-hidden="true"><svg width="100%" height="34" preserveAspectRatio="none"><defs><pattern id="bone" width="150" height="34" patternUnits="userSpaceOnUse"><path d="M18 10 a7 7 0 1 1 10 -6 h94 a7 7 0 1 1 10 6 a7 7 0 1 1 -10 6 h-94 a7 7 0 1 1 -10 -6 z" transform="translate(0 7)" fill="#efe2c4"/><path d="M75 13 l-4 4 l4 4 l4 -4 z" fill="#c9b48b"/></pattern></defs><rect width="100%" height="34" fill="url(#bone)"/></svg></div>;
}
// Games counted in the events score, shown on the card so the ranking signal is visible.
function GameRow({r}:{r:Rec}){
 const games=(r.score.components.events?.raw?.games as string[]|undefined)??[];
 if(!games.length) return null;
 return <div className="event-row"><span className="event-label">Game nearby:</span>{games.map(g=><span key={g}>{g}</span>)}</div>;
}
// Tiger Data: how this line ran at this station, same direction, in the last 12 hours; the API only sends it once enough trains have run.
const lateness=(m:number)=>Math.abs(m)<1?'on time on average':`ran ${Math.round(Math.abs(m))} min ${m>0?'late':'early'} on average`;
function TransitRow({r}:{r:Rec}){
 const out=r.reachability.outbound, last=r.reachability.last_return;
 if(!out?.line) return null;
 const ride=rideMin(out);
 return <div className="transit-row"><span className="line-pill" style={{background:out.line.color,color:out.line.mode==='bus'?'#141414':'#fff'}}>{out.line.name}</span><span className="transit-stops">{r.reachability.walk_to_stop_min!=null?`${r.reachability.walk_to_stop_min} min walk · `:''}{out.from_stop} → {out.to_stop}{ride?` · ${ride} min ride`:''}{r.reachability.walk_from_stop_min!=null?` · ${r.reachability.walk_from_stop_min} min walk`:''}</span>{last?.depart_at&&<span className="last-train"><Moon size={13} strokeWidth={2.5}/> {last.last_of_night?'Last train back':'Latest train back'} {clock(last.depart_at)}{last.reliability&&` · ${lateness(last.reliability.avg_delay_min)} in the last 12 h (${last.reliability.trains} trains)`}</span>}</div>;
}
const sourceNames:Record<string,string>={google_places:'Google Places',mbta:'MBTA',nws:'National Weather Service',boston_ckan:'Boston Open Data',sports:'Red Sox & Bruins schedules',overpass:'OpenStreetMap',tiktok:'TikTok taste'};
const futureTime=()=>{const d=new Date(Date.now()+2*60*60*1000);d.setMinutes(0,0,0);const p=(n:number)=>String(n).padStart(2,'0');return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:00`};

function loadSaved():SavedPlace[]{
  try{const raw=localStorage.getItem(SAVED_KEY);if(!raw)return[];const parsed=JSON.parse(raw);return Array.isArray(parsed)?parsed.filter((x:SavedPlace)=>x&&typeof x.place_id==='string'&&typeof x.name==='string'&&Array.isArray(x.categories)&&x.categories.every((c:unknown)=>typeof c==='string')):[]}catch{return[]}
}
function persistSaved(items:SavedPlace[]){try{localStorage.setItem(SAVED_KEY,JSON.stringify(items))}catch{/* private mode or full storage: keep the in-memory list */}}
function placeIdFor(v:Venue){return v.source_refs?.find(r=>r.source==='google_places')?.external_id||v.id}
function tagsFromSaved(items:SavedPlace[]):string[]{
  const counts=new Map<string,number>();
  for(const item of items)for(const c of item.categories||[])counts.set(c,(counts.get(c)||0)+1);
  return [...counts.entries()].sort((a,b)=>b[1]-a[1]).map(([tag])=>tag).slice(0,12);
}

function App(){
 const [view,setView]=useState(location.hash==='#map'||location.hash==='#atlas'?'map':'planner');
 useEffect(()=>{const sync=()=>setView(location.hash==='#map'||location.hash==='#atlas'?'map':'planner');window.addEventListener('hashchange',sync);return ()=>window.removeEventListener('hashchange',sync)},[]);
 const [when,setWhen]=useState(futureTime()); const [budget,setBudget]=useState('$$'); const [walk,setWalk]=useState(30); const [travel,setTravel]=useState<'walk'|'walk_t'>('walk_t'); const [text,setText]=useState(''); const [weather,setWeather]=useState<'clear'|'rain'>('clear'); const [data,setData]=useState<Result|null>(null); const [health,setHealth]=useState<any[]>([]); const [loading,setLoading]=useState(false); const [expanded,setExpanded]=useState<string|null>(null); const [modal,setModal]=useState(false); const [loc,setLoc]=useState(center); const [error,setError]=useState(''); const [neighborhood,setNeighborhood]=useState<Neighborhood|null>(null); const [neighborhoodBusy,setNeighborhoodBusy]=useState(false); const [whys,setWhys]=useState<Record<string,string>>({});
 const [saved,setSaved]=useState<SavedPlace[]>(()=>loadSaved());
 const [showSaved,setShowSaved]=useState(false);
 const [tiktokTags,setTiktokTags]=useState<string[]>([]);
 const [tiktokMode,setTiktokMode]=useState<'disabled'|'demo'|'live'>('disabled');
 const [tiktokBusy,setTiktokBusy]=useState(false);
 const [placeMentions,setPlaceMentions]=useState<PlaceMention[]>([]);

 const savedTags=useMemo(()=>tagsFromSaved(saved),[saved]);
 const preferenceTags=useMemo(()=>{
   const seen=new Set<string>(); const out:string[]=[];
   for(const tag of [...tiktokTags,...savedTags]){if(!seen.has(tag)){seen.add(tag);out.push(tag)}}
   return out.slice(0,12);
 },[tiktokTags,savedTags]);
 const savedIds=useMemo(()=>new Set(saved.map(s=>s.place_id)),[saved]);
 const recsForMatch=data?.recommendations||[];
 const tiktokMatched=useMemo(()=>{
   return placeMentions.map(m=>{
     const hit=recsForMatch.find(r=>namesOverlap(m.name,r.venue.name));
     return {mention:m,venue:hit?.venue||null};
   });
 },[placeMentions,recsForMatch]);
 const tiktokMatchedIds=useMemo(()=>new Set(tiktokMatched.filter(x=>x.venue).map(x=>x.venue!.id)),[tiktokMatched]);

 function updateSaved(next:SavedPlace[]){setSaved(next);persistSaved(next)}
 function toggleSave(v:Venue){
   const id=placeIdFor(v);
   if(savedIds.has(id))updateSaved(saved.filter(s=>s.place_id!==id));
   else updateSaved([{place_id:id,name:v.name,categories:v.categories||[],address:v.address,price_level:v.price_level,saved_at:new Date().toISOString()},...saved]);
 }
 function unsave(id:string){updateSaved(saved.filter(s=>s.place_id!==id))}

 async function refreshTiktok(forceDemo=false){
  setTiktokBusy(true);
  try{
    const url=forceDemo?'/api/tiktok/preferences?demo=1':'/api/tiktok/preferences';
    const res=await fetch(url,{credentials:'include'});
    if(!res.ok){setTiktokTags([]);setPlaceMentions([]);setTiktokMode('disabled');return}
    const body=await res.json();
    setTiktokTags(Array.isArray(body.preference_tags)?body.preference_tags:[]);
    setPlaceMentions(Array.isArray(body.place_mentions)?body.place_mentions:[]);
    setTiktokMode(body.mode==='live'||body.mode==='demo'?body.mode:'disabled');
    setHealth(current=>{
      const next=[...current];
      for(const item of body.sources_used||[]){const index=next.findIndex(x=>x.source===item.source);if(index>=0)next[index]={...next[index],status:item.status};else next.push(item)}
      return next;
    });
  }catch{setTiktokTags([]);setPlaceMentions([]);setTiktokMode('disabled')}
  finally{setTiktokBusy(false)}
 }

 async function connectTiktok(){
  setTiktokBusy(true);
  try{
    const demo=await fetch('/api/tiktok/demo',{method:'POST',credentials:'include'});
    if(demo.ok){
      const body=await demo.json();
      if(body.connected&&((body.preference_tags||[]).length||(body.place_mentions||[]).length)){
        setTiktokTags(body.preference_tags||[]);
        setPlaceMentions(Array.isArray(body.place_mentions)?body.place_mentions:[]);
        setTiktokMode(body.mode==='live'?'live':'demo');
        setTiktokBusy(false);
        return;
      }
    }
  }catch{}
  setTiktokBusy(false);
  window.location.href='/api/tiktok/login';
 }

 async function disconnectTiktok(){
  await fetch('/api/tiktok/logout',{method:'POST',credentials:'include'}).catch(()=>{});
  setTiktokTags([]);setPlaceMentions([]);setTiktokMode('disabled');setHealth(h=>h.map(x=>x.source==='tiktok'?{...x,status:'disabled'}:x));
 }

 const loadRef=useRef(load);
 async function load(){
  setLoading(true);setError('');
  try{
    const res=await fetch('/api/query',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({time:new Date(when).toISOString(),budget,lat:loc[0],lng:loc[1],max_walk_min:walk,travel,free_text:text||undefined,weather_override:weather==='rain'?'rain':undefined,preference_tags:preferenceTags.length?preferenceTags:undefined})});
    if(res.status===429)throw new Error('Too many searches right now. Please wait a minute and try again.');
    if(!res.ok)throw new Error('Could not load recommendations.');
    const result:Result=await res.json();
    setData(result);
    setHealth(current=>{const next=[...current];for(const item of result.sources_used){const index=next.findIndex(x=>x.source===item.source);if(index>=0)next[index]={...next[index],status:item.status};else next.push(item)}return next});
  }catch(e){setError(e instanceof Error?e.message:'Could not reach the Navigator API. Start the backend on port 8000.')}
  finally{setLoading(false)}
 }

 useEffect(()=>{
  const params=new URLSearchParams(window.location.search);
  const flag=params.get('tiktok');
  if(flag){window.history.replaceState({},'',window.location.pathname);if(flag==='demo')refreshTiktok(true);else if(flag==='connected'||flag==='error')refreshTiktok()}
  else refreshTiktok();
 },[]);
 useEffect(()=>{const refresh=()=>fetch('/api/sources/health').then(r=>r.json()).then(x=>setHealth(x.sources||[])).catch(()=>{});load();refresh();const timer=window.setInterval(refresh,30000);return()=>window.clearInterval(timer)},[]);
 loadRef.current=load;
 // wait for a pause so several quick hearts send one search, not one each (rate limit)
 useEffect(()=>{if(!data)return;const t=window.setTimeout(()=>loadRef.current(),800);return()=>window.clearTimeout(t)},[preferenceTags.join('|')]);
 useEffect(()=>{const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape'){setModal(false);setShowSaved(false)}};window.addEventListener('keydown',onKey);return()=>window.removeEventListener('keydown',onKey)},[]);

 async function showDetails(){setModal(true);setNeighborhoodBusy(true);try{const params=new URLSearchParams({lat:String(loc[0]),lng:String(loc[1]),radius_m:'1500'});const response=await fetch(`/api/neighborhood?${params}`);if(!response.ok)throw new Error('Neighborhood data is unavailable');const result:any=await response.json();setNeighborhood(result);setHealth(current=>{const next=[...current];for(const item of result.sources_used||[]){const index=next.findIndex(x=>x.source===item.source);if(index>=0)next[index]={...next[index],status:item.status};else next.push(item)}return next})}catch{setNeighborhood(null)}finally{setNeighborhoodBusy(false)}}
 const whyKey=(r:Rec)=>JSON.stringify(r.explain_facts);
 async function toggleWhy(r:Rec){const id=r.venue.id,key=whyKey(r);setExpanded(expanded===id?null:id);if(expanded===id||!r.explain_facts||key in whys)return;setWhys(w=>({...w,[key]:''}));try{const res=await fetch('/api/explain',{method:'POST',headers:{'Content-Type':'application/json'},body:key});const out=await res.json();if(res.ok&&out.explanation)setWhys(w=>({...w,[key]:out.explanation}))}catch{}}
 const recs=data?.recommendations||[];
 return <div className="app-shell">
  <header className={`topbar ${view==='map'?'':'over-hero'}`}>
   <a className="brand" href="#"><Dino size={46}/><span>T-Recs</span></a>
   <nav className="stops" aria-label="Sections">{[['#plan','Plan'],['#shortlist','Shortlist'],['#sources','Sources'],['#map','Map']].map(([h,l])=><a key={h} href={h} className={`stop ${l==='Map'?'map-stop':''}`} aria-current={view==='map'&&l==='Map'?'page':undefined}>{l}</a>)}</nav>
   <div className="top-actions">
    <button className={`icon-button ${showSaved?'is-active':''}`} aria-label="Open saved places" aria-expanded={showSaved} onClick={()=>setShowSaved(true)}><Bookmark size={18} strokeWidth={2.5}/></button>
    <button className="icon-button" aria-label="Open source information" onClick={showDetails}><SlidersHorizontal size={18} strokeWidth={2.5}/></button>
   </div>
  </header>
  <main>
   {view==='map'?<Suspense fallback={<p role="status">Loading Boston map…</p>}><AtlasView/></Suspense>:<>
   <section className="hero"><GardenScene/>
    <div className="hero-copy-wrap"><div className="eyebrow">T-RECS · RECS, BY T</div><h1>Find your spot</h1><p className="hero-copy">Good food. T-Recs has the ride.</p></div>
   </section>
   <Bones/>
   <section id="plan" className="planner sketch"><div className="planner-head"><Dino size={54}/><div><span className="section-kicker">STEP 1</span><h2>What are you craving?</h2></div></div>
    <div className="sign-body"><div className="form-grid"><label className="field field-wide"><span>THE VIBE</span><div className="input-wrap"><Sparkles size={16} strokeWidth={2.5}/><input value={text} onChange={e=>setText(e.target.value)} placeholder="cheap ramen, live music, somewhere cozy…" onKeyDown={e=>e.key==='Enter'&&load()}/><kbd>↵</kbd></div></label>
    <label className="field"><span>WHEN</span><div className="input-wrap"><Moon size={15} strokeWidth={2.5}/><input type="datetime-local" value={when} onChange={e=>setWhen(e.target.value)}/></div></label>
    <div className="field"><span>SPEND</span><div className="segmented">{['$','$$','$$$'].map(b=><button className={budget===b?'selected':''} key={b} onClick={()=>setBudget(b)}>{b}</button>)}</div></div>
    <div className="field field-wide"><span>HOW LONG TO GET THERE <b>{walk} MIN {travel==='walk_t'?'DOOR TO DOOR':'ON FOOT'}</b></span><div className="travel-row"><div className="segmented travel-toggle" role="group" aria-label="How you'll get there">{([['walk','Walk only'],['walk_t','Walk + T']] as const).map(([k,l])=><button key={k} className={travel===k?'selected':''} aria-pressed={travel===k} onClick={()=>setTravel(k)}>{k==='walk_t'?<TrainFront size={14} strokeWidth={2.5}/>:<Footprints size={14} strokeWidth={2.5}/>}{l}</button>)}</div><div className="slider-col"><input className="range" aria-label="Trip time in minutes" type="range" min="5" max="60" step="5" value={walk} onChange={e=>setWalk(+e.target.value)} style={{'--fill':`${(walk-5)/55*100}%`} as React.CSSProperties}/><div className="range-labels"><span>QUICK HOP</span><span>WORTH THE RIDE</span></div></div></div></div>
    </div>
    <div className={`taste-card ${tiktokMode!=='disabled'?'is-connected':''}`}>
     <div className="taste-card-glow" aria-hidden="true"/>
     <div className="taste-card-icon" aria-hidden="true"><Music2 size={22} strokeWidth={2.5}/></div>
     <div className="taste-meta">
      <span className="section-kicker">{tiktokMode==='disabled'?'UNLOCK YOUR VIBE':'TASTE CONNECTED'}</span>
      <strong className="taste-title">{tiktokMode==='disabled'?'Connect TikTok for a personal fit':'Your TikTok taste is live'}</strong>
      {preferenceTags.length
        ? <div className="taste-chips">{preferenceTags.map(t=><span key={t}>{t.replace('_',' ')}</span>)}</div>
        : <p className="taste-empty">{tiktokMode==='disabled'?'One tap pulls vibe tags from your videos and ranks spots that match.':'Save places too — categories boost the same taste score.'}</p>}
     </div>
     {tiktokMode==='disabled'
       ? <button className="tiktok-connect" onClick={connectTiktok} disabled={tiktokBusy}>
          <span className="tiktok-connect-shine" aria-hidden="true"/>
          <Music2 size={18} strokeWidth={2.5}/>
          {tiktokBusy?'Connecting…':'Connect TikTok'}
         </button>
       : <button className="ghost-button tiktok-disconnect" onClick={disconnectTiktok}>Disconnect · {tiktokMode}</button>}
    </div>
    <div className="form-footer"><div className="location-pill"><MapPin size={15} strokeWidth={2.5}/><span>Downtown Boston</span><button aria-label="Use current location" onClick={()=>navigator.geolocation?.getCurrentPosition(p=>setLoc([p.coords.latitude,p.coords.longitude]))}><Crosshair size={14} strokeWidth={2.5}/></button></div><button className="submit-button" onClick={load} disabled={loading}>{loading?'Finding places…':'Find spots'} <ArrowUpRight size={18} strokeWidth={3}/></button></div></div>
   </section>
   <div className="section-head" id="shortlist"><div><span className="section-kicker">YOUR SHORTLIST</span><h2>{text?'A few good fits.':'Good spots nearby.'}</h2></div><button className="weather-toggle" onClick={()=>setWeather(weather==='clear'?'rain':'clear')}>{weather==='clear'?<Moon size={16} strokeWidth={2.5}/>:<CloudRain size={16} strokeWidth={2.5}/>}{weather==='clear'?'Clear skies':'Rain check'}</button></div>
   {error&&<div className="notice error sketch">{error}</div>}
   {data?.empty_message&&<div className="empty sketch"><Dino size={64}/><p>{data.empty_message}</p></div>}
   <div className="content-grid"><section className="results-list">
    {recs.map((r,i)=>{const line=r.reachability.outbound?.line;const band=line?line.color:'#24704a';const dark=line?.mode==='bus';return <article id={`venue-${r.venue.id}`} className={`venue-card sketch ${expanded===r.venue.id?'expanded':''}`} key={r.venue.id}>
    <div className="sign-band venue-band" style={{background:band,color:dark?'#141414':'#fff'}}><div><div className="tags"><span>{String(i+1).padStart(2,'0')}</span><span>{r.venue.categories[0]?.replaceAll('_',' ')||'local favorite'}</span><span>{'$'.repeat(r.venue.price_level||1)}</span>{tiktokMatchedIds.has(r.venue.id)?<span className="tiktok-badge">From your TikTok</span>:null}</div><h3>{r.venue.name}</h3></div>{line?<Trolley color={line.color} size={52}/>:<Steps/>}</div>
    <div className="sign-body"><div className="venue-top"><p className="venue-address">{r.venue.address}</p><button className={`heart ${savedIds.has(placeIdFor(r.venue))?'is-saved':''}`} aria-pressed={savedIds.has(placeIdFor(r.venue))} aria-label={`${savedIds.has(placeIdFor(r.venue))?'Remove':'Save'} ${r.venue.name}`} onClick={()=>toggleSave(r.venue)}><Heart size={18} strokeWidth={2.5}/></button></div>
    <div className="venue-stats"><span><span className="star">★</span> {r.venue.rating?.toFixed(1)||'—'} <small>({r.venue.review_count?.toLocaleString()||'—'})</small></span><span><MapPin size={13} strokeWidth={2.5}/> {line&&r.reachability.total_min!=null?`${r.reachability.total_min} min by T`:`${r.venue.walk_min} min walk${r.venue.walk_estimate?.label==='approx.'?' (approx.)':''}`}</span><span><TrainFront size={14} strokeWidth={2.5}/> {r.reachability.method==='predicted_round_trip'?'Live round trip':r.reachability.method==='scheduled_round_trip'?'Scheduled round trip':r.reachability.method==='walking_fallback'?'On foot':'Transit check'}</span><span className="open-status">OPEN</span></div>
    <TransitRow r={r}/><GameRow r={r}/>
    <div className="score-row"><div className="score"><strong>{Math.round(r.score.value*100)}</strong><small>FIT</small></div><div className="score-track"><div style={{width:`${Math.round(r.score.value*100)}%`}}/></div><button className="why-button" onClick={()=>toggleWhy(r)}>Why this? <ChevronDown size={14} strokeWidth={2.5}/></button></div>{expanded===r.venue.id&&<div className="breakdown"><p>{whys[whyKey(r)]||r.explanation}{whys[whyKey(r)]&&<small> · AI summary from the facts below</small>}</p><p>{r.reach_explanation}</p>{Object.entries(r.score.components).map(([name,c])=><div className="component" key={name}><span>{name}<small>{c.missing_reason?` · not used (${c.missing_reason})`:c.label==='approx.'?' · approx.':c.label==='demo'?' · demo':''}</small></span><div><i style={{width:`${Math.round(c.value*100)}%`}}/></div><b>{Math.round(c.value*100)}<small> × {c.weight.toFixed(2)}</small></b></div>)}</div>}
    <div className="attribution" translate="no">{(r.venue.attributions||[]).map((a,i)=><span key={`${a.source}-${i}`}>{a.url?<a href={a.url} target="_blank" rel="noreferrer">{a.text}</a>:a.text}{i<(r.venue.attributions.length-1)?' · ':''}</span>)}</div></div></article>})}
    {placeMentions.length>0&&<div className="tiktok-places sketch" aria-label="From your TikTok">
      <span className="section-kicker">FROM YOUR TIKTOK</span>
      <div className="tiktok-place-list">
       {tiktokMatched.map(({mention,venue})=>venue
         ? <button key={`m-${mention.name}`} className="tiktok-place matched" type="button" onClick={()=>document.getElementById(`venue-${venue.id}`)?.scrollIntoView({behavior:'smooth',block:'center'})}>
            <b>{venue.name}</b>
           </button>
         : <div key={`u-${mention.name}`} className="tiktok-place"><b>{mention.name}</b></div>)}
      </div>
     </div>}
    </section>
   <aside className="map-column"><button className="neighborhood sketch" onClick={showDetails}><span className="neighborhood-icon"><Utensils size={18} strokeWidth={2.5}/></span><span><small>GET TO KNOW THE BLOCK</small><b>Neighborhood notes</b></span><ChevronRight size={18} strokeWidth={2.5}/></button><button className="neighborhood sketch saved-launch" onClick={()=>setShowSaved(true)}><span className="neighborhood-icon"><Bookmark size={18} strokeWidth={2.5}/></span><span><small>YOUR LIST</small><b>{saved.length?`${saved.length} saved place${saved.length===1?'':'s'}`:'Saved places'}</b></span><ChevronRight size={18} strokeWidth={2.5}/></button><div className="legend sketch"><span className="section-kicker">T LINE COLORS</span>{[['Red Line','#DA291C'],['Orange Line','#ED8B00'],['Green Line','#00843D'],['Blue Line','#003DA5'],['Silver Line','#7C878E'],['Bus','#FFC72C']].map(([n,c])=><div key={n} className="legend-row"><i style={{background:c}}/>{n}</div>)}</div></aside></div>
   <section id="sources" className="sources sketch"><div className="sources-title"><span className="section-kicker">THE SIGNAL CHECK</span><h3>Where this comes from.</h3></div><div className="source-items">{['google_places','mbta','nws','boston_ckan','sports','tiktok',...(health.some(h=>h.source==='overpass'&&h.status!=='disabled')?['overpass']:[])].map(s=>{const item=health.find(h=>h.source===s);return <div className="source-item" key={s}><span className={`source-dot ${item?.status==='live'?'is-live':''}`}/><span>{sourceNames[s]}</span><small>{item?.status||'demo'}</small></div>})}</div><p className="freshness">Source states and timestamps reflect the latest API response. Demo fixtures are labeled; live credentials stay server-side. TikTok personalizes taste tags; caption place names are best-effort guesses, not official TikTok venues.</p><p className="attribution"><a href="https://www.weather.gov/" target="_blank" rel="noreferrer">Weather data by the National Weather Service</a> · <a href="https://www.mbta.com/developers/v3-api" target="_blank" rel="noreferrer">MBTA</a> · <a href="https://data.boston.gov/" target="_blank" rel="noreferrer">City of Boston Open Data</a>{health.some(h=>h.source==='overpass'&&h.status!=='disabled')?<> · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a></>:null}</p></section>
  </>}
  </main><footer><span>T-RECS © 2026</span><span>MADE FOR THE WAY HOME <ArrowDownRight size={14} strokeWidth={2.5}/></span></footer>
  {modal&&<div className="modal-backdrop" onClick={()=>setModal(false)}><section className="modal sketch" role="dialog" aria-modal="true" aria-labelledby="details-title" onClick={e=>e.stopPropagation()}><button className="modal-close" aria-label="Close" autoFocus onClick={()=>setModal(false)}><X size={18} strokeWidth={2.5}/></button><span className="section-kicker">SOURCE DETAILS</span><h2 id="details-title">Trust, in the details.</h2><p>Recommendations use transparent fit scores and show whether source data is live, cached, demo, or unavailable.</p>{health.map(h=><div className="health-row" key={h.source}><span className={`source-dot ${h.status==='live'?'is-live':''}`}/><b>{sourceNames[h.source]||h.source}</b><small>{h.status}</small></div>)}<hr/><span className="section-kicker">NEIGHBORHOOD SNAPSHOT</span>{neighborhoodBusy?<p>Loading Boston Open Data…</p>:neighborhood?.["311"]?<><p>311 requests · {neighborhood["311"].period_start} to {neighborhood["311"].period_end}</p>{neighborhood["311"].top_categories.map(item=><div className="health-row" key={item.category}><b>{item.category}</b><small>{item.count}</small></div>)}<p>Recent {neighborhood.business_licenses_source||'business'}</p>{(neighborhood.business_licenses||[]).slice(0,5).map((item,i)=><div className="health-row" key={`${item.name}-${i}`}><b>{item.name||"Business"}</b><small>{item.issued_at}</small></div>)}{(neighborhood.city_contacts||[]).map(c=><p key={c.name}><a href={c.url}>{c.name}</a> · {c.phone}</p>)}</>:<p>Boston Open Data is unavailable right now. No neighborhood figures are being substituted.</p>}</section></div>}
  {showSaved&&<div className="modal-backdrop" onClick={()=>setShowSaved(false)}><section className="modal sketch saved-modal" role="dialog" aria-modal="true" aria-labelledby="saved-title" onClick={e=>e.stopPropagation()}><button className="modal-close" aria-label="Close saved places" autoFocus onClick={()=>setShowSaved(false)}><X size={18} strokeWidth={2.5}/></button><span className="section-kicker">SAVED PLACES</span><h2 id="saved-title">Your shortlist.</h2><p>Saved on this device only. Categories from these places feed taste scoring with TikTok tags.</p>{saved.length===0?<div className="empty sketch"><Heart size={20} strokeWidth={2.5}/><p>No saved places yet. Tap the heart on a recommendation to keep it here.</p></div>:saved.map(item=><div className="saved-row" key={item.place_id}><div><b>{item.name}</b><small>{(item.categories||[]).slice(0,2).join(' · ')||'place'}{item.address?` · ${item.address}`:''}</small></div><button className="ghost-button" onClick={()=>unsave(item.place_id)}>Remove</button></div>)}</section></div>}
 </div>
}

createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>);
