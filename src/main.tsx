import { lazy, Suspense, StrictMode, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowDownRight, ArrowRight, ArrowUpRight, Bookmark, ChevronDown, ChevronRight, CloudRain, Compass, Crosshair, Footprints, Heart, MapPin, Moon, SlidersHorizontal, Sparkles, TrainFront, Utensils, X } from 'lucide-react';
import type React from 'react';
import '@fontsource/akshar/latin-500.css';
import '@fontsource/akshar/latin-600.css';
import '@fontsource/akshar/latin-700.css';
import '@fontsource/krona-one/latin-400.css';
import '@fontsource/noto-sans/latin-400.css';
import '@fontsource/noto-sans/latin-600.css';
import '@fontsource/noto-sans/latin-700.css';
import { Plasma, PlasmaProvider } from '@cruxgarden/plasma-ui';
import './style.css';
const AtlasView = lazy(() => import('./AtlasView'));


type Venue={id:string;name:string;lat:number;lng:number;address:string|null;categories:string[];price_level:number|null;rating:number|null;review_count:number|null;walk_min:number;walk_estimate?:{label:string|null};indoor_outdoor:string;attributions:{source:string;text:string;url?:string;required_logo?:string;translate_no?:boolean}[];source_refs?:{source:string;external_id:string}[]};
type Line={id:string;name:string;color:string;mode:string};
type Leg={route?:string;line?:Line;from_stop?:string;to_stop?:string;depart_at?:string;arrive_at?:string;transfer?:{at:string;line:Line}};
type Rec={venue:Venue;reachability:{method:string;label?:string;outbound?:Leg|null;return?:Leg|null;last_return?:(Leg&{last_of_night?:boolean})|null;total_min?:number|null;walk_to_stop_min?:number;walk_from_stop_min?:number};score:{value:number;components:Record<string,{value:number;weight:number;base_weight?:number;label?:string;missing_reason?:string|null;raw:Record<string,unknown>;sources:string[]}>};explanation:string;reach_explanation?:string;explain_facts?:Record<string,unknown>};
type Result={recommendations:Rec[];sources_used:{source:string;status:string}[];generated_at:string;empty_message:string|null;query:{parsed_filters?:Record<string,unknown>;preference_tags?:string[]};weather:{temperature_f:number|null;precipitation_chance_pct:number|null;forecast_for?:string;override?:string}};
type Neighborhood={center:{lat:number;lng:number};radius_m:number;311:{top_categories:{category:string;count:number}[];period_start:string;period_end:string}|null;business_licenses:{name:string;issued_at:string;address?:string;distance_m?:number}[]|null;business_licenses_source?:string|null;city_contacts:{name:string;service:string;phone:string;url:string}[]|null};
type SavedPlace={place_id:string;name:string;categories:string[];address:string|null;price_level:number|null;saved_at:string};

const SAVED_KEY='boundless.savedPlaces.v1';
const center:[number,number]=[42.355,-71.062];
const clock=(iso?:string)=>iso?new Date(iso).toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit',timeZone:'America/New_York'}):'';
const rideMin=(leg:Leg)=>leg.depart_at&&leg.arrive_at?Math.max(1,Math.round((Date.parse(leg.arrive_at)-Date.parse(leg.depart_at))/60000)):null;
// Hand-drawn doodles (own artwork): ink strokes, flat MBTA colors.
const INK='#141414';
function Trolley({color='#DA291C',size=56}:{color?:string;size?:number}){
 return <svg className="doodle" width={size} height={size*60/64} viewBox="0 0 64 60" aria-hidden="true" filter="url(#wobble)">
  <path d="M24 9 L32 2 L40 9" fill="none" stroke={INK} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
  <rect x="9" y="9" width="46" height="38" rx="9" fill="#f4f3ee" stroke={INK} strokeWidth="2.5"/>
  <rect x="9" y="30" width="46" height="9" fill={color} stroke={INK} strokeWidth="2.5"/>
  <rect x="15" y="15" width="14" height="10" rx="3" fill={INK}/><rect x="35" y="15" width="14" height="10" rx="3" fill={INK}/>
  <circle cx="16" cy="34.5" r="2.2" fill="#fff8d6" stroke={INK} strokeWidth="1.2"/><circle cx="48" cy="34.5" r="2.2" fill="#fff8d6" stroke={INK} strokeWidth="1.2"/>
  <circle cx="20" cy="51" r="4.5" fill="#fff" stroke={INK} strokeWidth="2.5"/><circle cx="44" cy="51" r="4.5" fill="#fff" stroke={INK} strokeWidth="2.5"/>
  <path d="M3 57 H61" stroke={INK} strokeWidth="2.5" strokeLinecap="round"/>
 </svg>;
}
function Steps(){
 return <svg className="doodle" width="46" height="46" viewBox="0 0 46 46" aria-hidden="true" filter="url(#wobble)">
  <g fill="#fff" stroke={INK} strokeWidth="2.2"><ellipse cx="14" cy="30" rx="5.5" ry="8.5" transform="rotate(-12 14 30)"/><ellipse cx="31" cy="15" rx="5.5" ry="8.5" transform="rotate(-12 31 15)"/></g>
  <g fill={INK}><circle cx="11" cy="18.5" r="1.6"/><circle cx="15" cy="17.5" r="1.6"/><circle cx="18.5" cy="19" r="1.4"/><circle cx="28" cy="3.8" r="1.6"/><circle cx="32" cy="2.8" r="1.6"/><circle cx="35.5" cy="4.3" r="1.4"/></g>
 </svg>;
}
function HeroDoodle(){
 return <svg className="hero-doodle" viewBox="0 0 440 250" role="img" aria-label="A trolley rolling past the Boston skyline at night" filter="url(#wobble)">
  <g fill="none" stroke={INK} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
   <circle cx="372" cy="44" r="22" fill="#ffe08a"/><path d="M380 26 a22 22 0 0 1 0 36 a26 26 0 0 0 0 -36z" fill="#f4f3ee"/>
   <path d="M60 40 v10 M55 45 h10 M300 22 v8 M296 26 h8 M150 30 v8 M146 34 h8"/>
   <path d="M228 62 q-14 0 -14 -12 q0 -14 16 -12 q4 -12 18 -10 q14 2 12 14 q12 0 10 10 q-2 10 -14 10z" fill="#fff"/>
   <path d="M20 190 V120 h44 v70" fill="#fff"/><path d="M20 120 l22 -18 l22 18" fill="#fff"/>
   <path d="M30 138 h8 v10 h-8z M46 138 h8 v10 h-8z M30 160 h8 v10 h-8z M46 160 h8 v10 h-8z"/>
   <path d="M76 190 V128 h70 v62" fill="#fff"/><path d="M84 128 q27 -40 54 0" fill="#f2c14e"/><path d="M111 88 v-10 M107 82 h8"/><path d="M88 146 v30 M100 146 v30 M112 146 v30 M124 146 v30 M136 146 v30"/>
   <path d="M160 190 V70 l34 -8 V190" fill="#dcecf6"/><path d="M168 82 l18 -4 M168 100 l18 -4 M168 118 l18 -4 M168 136 l18 -4 M168 154 l18 -4"/>
   <path d="M206 190 V104 h42 V190" fill="#fff"/><path d="M212 104 v-12 h30 v12 M218 92 v-8 h18 v8 M227 84 v-14"/><path d="M216 120 h22 M216 138 h22 M216 156 h22"/>
   <path d="M262 190 V140 h30 V190" fill="#fff"/><path d="M262 140 l15 -12 l15 12" fill="#fff"/>
   <path d="M306 190 l26 -70 l26 70 M332 120 l-16 70 M332 120 l16 70 M332 120 v70" /><path d="M296 168 q36 -16 72 0"/>
   <circle cx="398" cy="168" r="16" fill="#9fd08a"/><path d="M398 184 v8"/>
  </g>
  <path d="M8 222 H432" stroke={INK} strokeWidth="3"/><path d="M8 232 H432" stroke={INK} strokeWidth="3"/>
  <path d="M20 218 v18 M48 218 v18 M76 218 v18 M104 218 v18 M132 218 v18 M160 218 v18 M188 218 v18 M216 218 v18 M244 218 v18 M272 218 v18 M300 218 v18 M328 218 v18 M356 218 v18 M384 218 v18 M412 218 v18" stroke="#9a9a96" strokeWidth="3"/>
  <g transform="translate(230 166)"><path d="M14 4 L22 -4 L30 4" fill="none" stroke={INK} strokeWidth="2.5"/><rect x="0" y="4" width="62" height="44" rx="10" fill="#f4f3ee" stroke={INK} strokeWidth="2.5"/><rect x="0" y="30" width="62" height="9" fill="#00843D" stroke={INK} strokeWidth="2.5"/><rect x="7" y="11" width="13" height="12" rx="3" fill={INK}/><rect x="25" y="11" width="13" height="12" rx="3" fill={INK}/><rect x="43" y="11" width="13" height="12" rx="3" fill={INK}/><circle cx="14" cy="52" r="5" fill="#fff" stroke={INK} strokeWidth="2.5"/><circle cx="48" cy="52" r="5" fill="#fff" stroke={INK} strokeWidth="2.5"/></g>
  <path d="M200 196 h-14 M204 206 h-24 M198 186 h-8" stroke={INK} strokeWidth="2.5" strokeLinecap="round"/>
 </svg>;
}
// Games counted in the events score, shown on the card so the ranking signal is visible.
function GameRow({r}:{r:Rec}){
 const games=(r.score.components.events?.raw?.games as string[]|undefined)??[];
 if(!games.length) return null;
 return <div className="event-row"><span className="event-label">Game nearby:</span>{games.map(g=><span key={g}>{g}</span>)}</div>;
}
function TransitRow({r}:{r:Rec}){
 const out=r.reachability.outbound, last=r.reachability.last_return;
 if(!out?.line) return null;
 const ride=rideMin(out);
 return <div className="transit-row"><span className="line-pill" style={{background:out.line.color,color:out.line.mode==='bus'?'#141414':'#fff'}}>{out.line.name}</span><span className="transit-stops">{r.reachability.walk_to_stop_min!=null?`${r.reachability.walk_to_stop_min} min walk · `:''}{out.from_stop} → {out.to_stop}{ride?` · ${ride} min ride`:''}{r.reachability.walk_from_stop_min!=null?` · ${r.reachability.walk_from_stop_min} min walk`:''}</span>{last?.depart_at&&<span className="last-train"><Moon size={13} strokeWidth={2.5}/> {last.last_of_night?'Last train back':'Latest train back'} {clock(last.depart_at)}</span>}</div>;
}
const sourceNames:Record<string,string>={google_places:'Google Places',mbta:'MBTA',nws:'National Weather Service',boston_ckan:'Boston Open Data',sports:'Red Sox & Bruins schedules',overpass:'OpenStreetMap (backup)',tiktok:'TikTok taste'};
const futureTime=()=>{const d=new Date(Date.now()+2*60*60*1000);d.setMinutes(0,0,0);const p=(n:number)=>String(n).padStart(2,'0');return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:00`};

function loadSaved():SavedPlace[]{
  try{const raw=localStorage.getItem(SAVED_KEY);if(!raw)return[];const parsed=JSON.parse(raw);return Array.isArray(parsed)?parsed.filter((x:SavedPlace)=>x&&typeof x.place_id==='string'):[]}catch{return[]}
}
function persistSaved(items:SavedPlace[]){localStorage.setItem(SAVED_KEY,JSON.stringify(items))}
function placeIdFor(v:Venue){return v.source_refs?.find(r=>r.source==='google_places')?.external_id||v.id}
function tagsFromSaved(items:SavedPlace[]):string[]{
  const counts=new Map<string,number>();
  for(const item of items)for(const c of item.categories||[])counts.set(c,(counts.get(c)||0)+1);
  return [...counts.entries()].sort((a,b)=>b[1]-a[1]).map(([tag])=>tag).slice(0,12);
}

function App(){
 const [view,setView]=useState(location.hash==='#atlas'?'atlas':'planner');
 useEffect(()=>{const sync=()=>setView(location.hash==='#atlas'?'atlas':'planner');window.addEventListener('hashchange',sync);return ()=>window.removeEventListener('hashchange',sync)},[]);
 const [when,setWhen]=useState(futureTime()); const [budget,setBudget]=useState('$$'); const [walk,setWalk]=useState(30); const [travel,setTravel]=useState<'walk'|'walk_t'>('walk_t'); const [text,setText]=useState(''); const [weather,setWeather]=useState<'clear'|'rain'>('clear'); const [data,setData]=useState<Result|null>(null); const [health,setHealth]=useState<any[]>([]); const [loading,setLoading]=useState(false); const [expanded,setExpanded]=useState<string|null>(null); const [modal,setModal]=useState(false); const [loc,setLoc]=useState(center); const [error,setError]=useState(''); const [neighborhood,setNeighborhood]=useState<Neighborhood|null>(null); const [neighborhoodBusy,setNeighborhoodBusy]=useState(false); const [whys,setWhys]=useState<Record<string,string>>({});
 const [saved,setSaved]=useState<SavedPlace[]>(()=>loadSaved());
 const [showSaved,setShowSaved]=useState(false);
 const [tiktokTags,setTiktokTags]=useState<string[]>([]);
 const [tiktokMode,setTiktokMode]=useState<'disabled'|'demo'|'live'>('disabled');
 const [tiktokBusy,setTiktokBusy]=useState(false);

 const savedTags=useMemo(()=>tagsFromSaved(saved),[saved]);
 const preferenceTags=useMemo(()=>{
   const seen=new Set<string>(); const out:string[]=[];
   for(const tag of [...tiktokTags,...savedTags]){if(!seen.has(tag)){seen.add(tag);out.push(tag)}}
   return out.slice(0,12);
 },[tiktokTags,savedTags]);
 const savedIds=useMemo(()=>new Set(saved.map(s=>s.place_id)),[saved]);

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
    if(!res.ok){setTiktokTags([]);setTiktokMode('disabled');return}
    const body=await res.json();
    setTiktokTags(Array.isArray(body.preference_tags)?body.preference_tags:[]);
    setTiktokMode(body.mode==='live'||body.mode==='demo'?body.mode:'disabled');
    setHealth(current=>{
      const next=[...current];
      for(const item of body.sources_used||[]){const index=next.findIndex(x=>x.source===item.source);if(index>=0)next[index]={...next[index],status:item.status};else next.push(item)}
      return next;
    });
  }catch{setTiktokTags([]);setTiktokMode('disabled')}
  finally{setTiktokBusy(false)}
 }

 async function connectTiktok(){
  setTiktokBusy(true);
  try{
    const demo=await fetch('/api/tiktok/demo',{method:'POST',credentials:'include'});
    if(demo.ok){
      const body=await demo.json();
      if(body.connected&&(body.preference_tags||[]).length){
        setTiktokTags(body.preference_tags||[]);
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
  setTiktokTags([]);setTiktokMode('disabled');
 }

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
 useEffect(()=>{if(data)load()},[preferenceTags.join('|')]);

 async function showDetails(){setModal(true);setNeighborhoodBusy(true);try{const params=new URLSearchParams({lat:String(loc[0]),lng:String(loc[1]),radius_m:'1500'});const response=await fetch(`/api/neighborhood?${params}`);if(!response.ok)throw new Error('Neighborhood data is unavailable');const result:any=await response.json();setNeighborhood(result);setHealth(current=>{const next=[...current];for(const item of result.sources_used||[]){const index=next.findIndex(x=>x.source===item.source);if(index>=0)next[index]={...next[index],status:item.status};else next.push(item)}return next})}catch{setNeighborhood(null)}finally{setNeighborhoodBusy(false)}}
 const whyKey=(r:Rec)=>JSON.stringify(r.explain_facts);
 async function toggleWhy(r:Rec){const id=r.venue.id,key=whyKey(r);setExpanded(expanded===id?null:id);if(expanded===id||!r.explain_facts||key in whys)return;setWhys(w=>({...w,[key]:''}));try{const res=await fetch('/api/explain',{method:'POST',headers:{'Content-Type':'application/json'},body:key});const out=await res.json();if(res.ok&&out.explanation)setWhys(w=>({...w,[key]:out.explanation}))}catch{}}
 const recs=data?.recommendations||[];
 return <div className="app-shell">
  <svg width="0" height="0" style={{position:'absolute'}} aria-hidden="true"><defs><filter id="wobble"><feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2" seed="7"/><feDisplacementMap in="SourceGraphic" scale="3.2"/></filter></defs></svg>
  <header className="topbar">
   <a className="brand" href="#"><Trolley color="#DA291C" size={34}/><span>boundless<span className="brand-dot">.</span></span></a>
   <nav className="stops" aria-label="Sections"><span className="rail"/>{[['#plan','Plan'],['#shortlist','Shortlist'],['#sources','Sources'],['#atlas','College Atlas']].map(([h,l])=><a key={h} href={h} className="stop"><span className="stop-dot"/><span className="stop-label">{l}</span></a>)}</nav>
   <div className="top-actions">
    <button className={`icon-button ${showSaved?'is-active':''}`} aria-label="Open saved places" onClick={()=>setShowSaved(true)}><Bookmark size={18} strokeWidth={2.5}/></button>
    <button className="icon-button" aria-label="Open source information" onClick={showDetails}><SlidersHorizontal size={18} strokeWidth={2.5}/></button>
   </div>
  </header>
  <main>
   {view==='atlas'?<Suspense fallback={<p role="status">Loading College Atlas…</p>}><AtlasView/></Suspense>:<>
   <section className="hero"><div className="hero-copy-wrap"><div className="eyebrow">BOSTON · TONIGHT · BY FOOT OR BY T</div><h1>Boston after <span className="squiggle">hours.</span></h1><p className="hero-copy">Good plans start with a place. Great ones get you home on the last train.</p></div><HeroDoodle/></section>
   <section id="plan" className="planner sketch"><div className="sign-band" style={{background:'#2b9bd8'}}><span>WHERE TO TONIGHT?</span><ArrowRight className="band-arrow" size={24} strokeWidth={3}/></div>
    <div className="sign-body"><div className="form-grid"><label className="field field-wide"><span>THE VIBE</span><div className="input-wrap"><Sparkles size={16} strokeWidth={2.5}/><input value={text} onChange={e=>setText(e.target.value)} placeholder="cheap ramen, live music, somewhere cozy…" onKeyDown={e=>e.key==='Enter'&&load()}/><kbd>↵</kbd></div></label>
    <label className="field"><span>WHEN</span><div className="input-wrap"><Moon size={15} strokeWidth={2.5}/><input type="datetime-local" value={when} onChange={e=>setWhen(e.target.value)}/></div></label>
    <div className="field"><span>SPEND</span><div className="segmented">{['$','$$','$$$'].map(b=><button className={budget===b?'selected':''} key={b} onClick={()=>setBudget(b)}>{b}</button>)}</div></div>
    <div className="field field-wide"><span>HOW LONG TO GET THERE <b>{walk} MIN {travel==='walk_t'?'DOOR TO DOOR':'ON FOOT'}</b></span><div className="travel-row"><div className="segmented travel-toggle" role="group" aria-label="How you'll get there">{([['walk','Walk only'],['walk_t','Walk + T']] as const).map(([k,l])=><button key={k} className={travel===k?'selected':''} aria-pressed={travel===k} onClick={()=>setTravel(k)}>{k==='walk_t'?<TrainFront size={14} strokeWidth={2.5}/>:<Footprints size={14} strokeWidth={2.5}/>}{l}</button>)}</div><div className="slider-col"><input className="range" aria-label="Trip time in minutes" type="range" min="5" max="60" step="5" value={walk} onChange={e=>setWalk(+e.target.value)} style={{'--fill':`${(walk-5)/55*100}%`} as React.CSSProperties}/><div className="range-labels"><span>QUICK HOP</span><span>WORTH THE RIDE</span></div></div></div></div>
    </div>
    <div className="taste-row">
     <div className="taste-meta">
      <span className="section-kicker">YOUR TASTE</span>
      {preferenceTags.length
        ? <div className="taste-chips">{preferenceTags.map(t=><span key={t}>{t.replace('_',' ')}</span>)}</div>
        : <p className="taste-empty">Connect TikTok or save places to personalize fit scores.</p>}
     </div>
     {tiktokMode==='disabled'
       ? <button className="ghost-button" onClick={connectTiktok} disabled={tiktokBusy}>{tiktokBusy?'Connecting…':'Connect TikTok'}</button>
       : <button className="ghost-button" onClick={disconnectTiktok}>Disconnect TikTok · {tiktokMode}</button>}
    </div>
    <div className="form-footer"><div className="location-pill"><MapPin size={15} strokeWidth={2.5}/><span>Downtown Boston</span><button aria-label="Use current location" onClick={()=>navigator.geolocation?.getCurrentPosition(p=>setLoc([p.coords.latitude,p.coords.longitude]))}><Crosshair size={14} strokeWidth={2.5}/></button></div><button className="submit-button" onClick={load} disabled={loading}>{loading?'Finding places…':'Find my night'} <ArrowUpRight size={18} strokeWidth={3}/></button></div></div>
   </section>
   <div className="section-head" id="shortlist"><div><span className="section-kicker">YOUR SHORTLIST</span><h2>{text?'A few good fits.':'The night is yours.'}</h2></div><button className="weather-toggle" onClick={()=>setWeather(weather==='clear'?'rain':'clear')}>{weather==='clear'?<Moon size={16} strokeWidth={2.5}/>:<CloudRain size={16} strokeWidth={2.5}/>}{weather==='clear'?'Clear skies':'Rain check'}</button></div>
   {error&&<div className="notice error sketch">{error}</div>}
   {data?.empty_message&&<div className="empty sketch"><Moon size={22} strokeWidth={2.5}/><p>{data.empty_message}</p></div>}
   <div className="content-grid"><section className="results-list">{recs.map((r,i)=>{const line=r.reachability.outbound?.line;const band=line?line.color:'#2b2b2b';const dark=line?.mode==='bus';return <article className={`venue-card sketch ${expanded===r.venue.id?'expanded':''}`} key={r.venue.id}>
    <div className="sign-band venue-band" style={{background:band,color:dark?'#141414':'#fff'}}><div><div className="tags"><span>{String(i+1).padStart(2,'0')}</span><span>{r.venue.categories[0]?.replace('_',' ')||'local favorite'}</span><span>{'$'.repeat(r.venue.price_level||1)}</span></div><h3>{r.venue.name}</h3></div>{line?<Trolley color={line.color} size={52}/>:<Steps/>}</div>
    <div className="sign-body"><div className="venue-top"><p className="venue-address">{r.venue.address}</p><button className={`heart ${savedIds.has(placeIdFor(r.venue))?'is-saved':''}`} aria-pressed={savedIds.has(placeIdFor(r.venue))} aria-label={`${savedIds.has(placeIdFor(r.venue))?'Remove':'Save'} ${r.venue.name}`} onClick={()=>toggleSave(r.venue)}><Heart size={18} strokeWidth={2.5}/></button></div>
    <div className="venue-stats"><span><span className="star">★</span> {r.venue.rating?.toFixed(1)||'—'} <small>({r.venue.review_count?.toLocaleString()||'—'})</small></span><span><MapPin size={13} strokeWidth={2.5}/> {line&&r.reachability.total_min!=null?`${r.reachability.total_min} min by T`:`${r.venue.walk_min} min walk${r.venue.walk_estimate?.label==='approx.'?' (approx.)':''}`}</span><span><TrainFront size={14} strokeWidth={2.5}/> {r.reachability.method==='predicted_round_trip'?'Live round trip':r.reachability.method==='scheduled_round_trip'?'Scheduled round trip':r.reachability.method==='walking_fallback'?'On foot':'Transit check'}</span><span className="open-status">OPEN</span></div>
    <TransitRow r={r}/><GameRow r={r}/>
    <div className="score-row"><div className="score"><strong>{Math.round(r.score.value*100)}</strong><small>FIT</small></div><div className="score-track"><div style={{width:`${Math.round(r.score.value*100)}%`}}/></div><button className="why-button" onClick={()=>toggleWhy(r)}>Why this? <ChevronDown size={14} strokeWidth={2.5}/></button></div>{expanded===r.venue.id&&<div className="breakdown"><p>{whys[whyKey(r)]||r.explanation}{whys[whyKey(r)]&&<small> · AI summary from the facts below</small>}</p><p>{r.reach_explanation}</p>{Object.entries(r.score.components).map(([name,c])=><div className="component" key={name}><span>{name}<small>{c.missing_reason?` · not used (${c.missing_reason})`:c.label==='approx.'?' · approx.':c.label==='demo'?' · demo':''}</small></span><div><i style={{width:`${Math.round(c.value*100)}%`}}/></div><b>{Math.round(c.value*100)}<small> × {c.weight.toFixed(2)}</small></b></div>)}</div>}
    <div className="attribution" translate="no">{(r.venue.attributions||[]).map((a,i)=><span key={`${a.source}-${i}`}>{a.url?<a href={a.url} target="_blank" rel="noreferrer">{a.text}</a>:a.text}{i<(r.venue.attributions.length-1)?' · ':''}</span>)}</div></div></article>})}</section>
   <aside className="map-column"><button className="neighborhood sketch" onClick={showDetails}><span className="neighborhood-icon"><Utensils size={18} strokeWidth={2.5}/></span><span><small>GET TO KNOW THE BLOCK</small><b>Neighborhood notes</b></span><ChevronRight size={18} strokeWidth={2.5}/></button><button className="neighborhood sketch saved-launch" onClick={()=>setShowSaved(true)}><span className="neighborhood-icon"><Bookmark size={18} strokeWidth={2.5}/></span><span><small>YOUR LIST</small><b>{saved.length?`${saved.length} saved place${saved.length===1?'':'s'}`:'Saved places'}</b></span><ChevronRight size={18} strokeWidth={2.5}/></button><div className="legend sketch"><span className="section-kicker">T LINE COLORS</span>{[['Red Line','#DA291C'],['Orange Line','#ED8B00'],['Green Line','#00843D'],['Blue Line','#003DA5'],['Silver Line','#7C878E'],['Bus','#FFC72C']].map(([n,c])=><div key={n} className="legend-row"><i style={{background:c}}/>{n}</div>)}</div></aside></div>
   <section id="sources" className="sources sketch"><div className="sources-title"><span className="section-kicker">THE SIGNAL CHECK</span><h3>Where this comes from.</h3></div><div className="source-items">{['google_places','mbta','nws','boston_ckan','sports','tiktok',...(health.some(h=>h.source==='overpass'&&h.status!=='disabled')?['overpass']:[])].map(s=>{const item=health.find(h=>h.source===s);return <div className="source-item" key={s}><span className={`source-dot ${item?.status==='live'||item?.status==='demo'?'is-live':''}`}/><span>{sourceNames[s]}</span><small>{item?.status||'demo'}</small></div>})}</div><p className="freshness">Source states and timestamps reflect the latest API response. Demo fixtures are labeled; live credentials stay server-side. TikTok is personalization only—not venue discovery.</p><p className="attribution"><a href="https://www.weather.gov/" target="_blank" rel="noreferrer">Weather data by the National Weather Service</a> · <a href="https://www.mbta.com/developers/v3-api" target="_blank" rel="noreferrer">MBTA</a> · <a href="https://data.boston.gov/" target="_blank" rel="noreferrer">City of Boston Open Data</a>{health.some(h=>h.source==='overpass'&&h.status!=='disabled')?<> · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a></>:null}</p></section>
  </>}
  </main><footer><span className="rail"/><span>BOUNDLESS BOSTON © 2026</span><span>MADE FOR THE WAY HOME <ArrowDownRight size={14} strokeWidth={2.5}/></span></footer>
  {modal&&view!=='atlas'&&<div className="modal-backdrop" onClick={()=>setModal(false)}><section className="modal sketch" onClick={e=>e.stopPropagation()}><button className="modal-close" aria-label="Close" onClick={()=>setModal(false)}><X size={18} strokeWidth={2.5}/></button><span className="section-kicker">SOURCE DETAILS</span><h2>Trust, in the details.</h2><p>Recommendations use transparent fit scores and show whether source data is live, cached, demo, or unavailable.</p>{health.map(h=><div className="health-row" key={h.source}><span className={`source-dot ${h.status==='live'||h.status==='demo'?'is-live':''}`}/><b>{sourceNames[h.source]||h.source}</b><small>{h.status}</small></div>)}<hr/><span className="section-kicker">NEIGHBORHOOD SNAPSHOT</span>{neighborhoodBusy?<p>Loading Boston Open Data…</p>:neighborhood?.["311"]?<><p>311 requests · {neighborhood["311"].period_start} to {neighborhood["311"].period_end}</p>{neighborhood["311"].top_categories.map(item=><div className="health-row" key={item.category}><b>{item.category}</b><small>{item.count}</small></div>)}<p>Recent {neighborhood.business_licenses_source||'business'}</p>{(neighborhood.business_licenses||[]).slice(0,5).map((item,i)=><div className="health-row" key={`${item.name}-${i}`}><b>{item.name||"Business"}</b><small>{item.issued_at}</small></div>)}{(neighborhood.city_contacts||[]).map(c=><p key={c.name}><a href={c.url}>{c.name}</a> · {c.phone}</p>)}</>:<p>Boston Open Data is unavailable right now. No neighborhood figures are being substituted.</p>}</section></div>}
  {showSaved&&<div className="modal-backdrop" onClick={()=>setShowSaved(false)}><section className="modal sketch saved-modal" onClick={e=>e.stopPropagation()}><button className="modal-close" aria-label="Close saved places" onClick={()=>setShowSaved(false)}><X size={18} strokeWidth={2.5}/></button><span className="section-kicker">SAVED PLACES</span><h2>Your shortlist.</h2><p>Saved on this device only. Categories from these places feed taste scoring with TikTok tags.</p>{saved.length===0?<div className="empty sketch"><Heart size={20} strokeWidth={2.5}/><p>No saved places yet. Tap the heart on a recommendation to keep it here.</p></div>:saved.map(item=><div className="saved-row" key={item.place_id}><div><b>{item.name}</b><small>{(item.categories||[]).slice(0,2).join(' · ')||'place'}{item.address?` · ${item.address}`:''}</small></div><button className="ghost-button" onClick={()=>unsave(item.place_id)}>Remove</button></div>)}</section></div>}
 </div>
}

createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>);
