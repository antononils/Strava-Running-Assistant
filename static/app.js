// === Elements ===
// Main UI nodes used across the script
const form = document.getElementById('chat-form');
const input = document.getElementById('message');
const sendBtn = document.getElementById('send-btn');
const out = document.getElementById('output');
const mapFrame = document.getElementById('map-frame');
const suggestions = document.getElementById('suggestions');
const micBtn = document.getElementById('mic-btn');


// === Helpers ===
// Track whether a request is in-flight (disables send, etc.)
let pending = false;

// Build a chat bubble element
function msgBubble(text, role = 'bot') {
  const d = document.createElement('div');
  d.className = `msg ${role}`;
  d.textContent = text;
  return d;
}


// === Formatters ===
// Format meters -> "X,XX km"
function formatDistance(meters){
  if(meters==null) return '—';
  return (meters/1000).toFixed(2).replace('.', ',') + ' km';
}

// Format elevation meters -> "X m"
function formatElevation(meters){
  if(meters==null) return '—';
  const v = Math.round(meters*10)/10;
  const s = (v % 1 === 0) ? v.toString() : v.toFixed(1);
  return s.replace('.', ',') + ' m';
}

// Format seconds -> "H h M min" or "M min"
function formatMovingTime(sec){
  if(sec==null) return '—';
  const h = Math.floor(sec/3600);
  const m = Math.floor((sec%3600)/60);
  if(h>0) return `${h} h ${m} min`;
  return `${m} min`;
}

// Calculate pace from distance and time -> "min/km"
function formatPace(distance_m, time_s){
  if(distance_m==null || time_s==null || distance_m<=0 || time_s<=0) return '—';
  const km = distance_m / 1000;
  const minPerKm = (time_s / 60) / km;
  let min = Math.floor(minPerKm);
  let sec = Math.round((minPerKm - min)*60);
  if(sec===60){ sec=0; min+=1; }
  return `${min}:${sec.toString().padStart(2,'0')} min/km`;
}

// Format heart rate -> "X bpm"
function formatHeartRate(bpm){
  if(bpm==null) return '—';
  return `${Math.round(bpm)} bpm`;
}

// Format ISO date -> {top: "12 okt", bottom: "2025"}
function formatDateOnly(iso){
  if(!iso) return { top:'—', bottom:'' };
  const d = new Date(iso);
  const months = ['jan','feb','mar','apr','maj','jun','jul','aug','sep','okt','nov','dec'];
  return { top: `${d.getDate()} ${months[d.getMonth()]}`, bottom: `${d.getFullYear()}` };
}


// === SVG icons ===
// Create a simple inline SVG with a given path
function svgIcon(pathD, viewBox='0 0 24 24'){
  const svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox', viewBox);
  svg.setAttribute('aria-hidden','true');
  svg.classList.add('metric-icon');
  const p = document.createElementNS('http://www.w3.org/2000/svg','path');
  p.setAttribute('d', pathD);
  p.setAttribute('fill','currentColor');
  svg.appendChild(p);
  return svg;
}

// Specific icon helpers for metrics
function iconDistance(){ return svgIcon('M4 6h16v2H4V6zm0 5h10v2H4v-2zm0 5h16v2H4v-2z'); }
function iconElevation(){ return svgIcon('M3 19l7-12 3 5 2-3 6 10H3z'); }
function iconSpeed(){ return svgIcon('M12 3a9 9 0 109 9h-2a7 7 0 11-7-7V3zm-1 9l6.5-3.75-1-1.73L11 10V12z'); }
function iconTime(){ return svgIcon('M12 2a10 10 0 100 20 10 10 0 000-20zm1 11h5v-2h-4V6h-2v7z'); }
function iconHeart(){ return svgIcon('M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 6.01 4.01 4 6.5 4 8.28 4 9.9 4.99 12 7.09 14.1 4.99 15.72 4 17.5 4 19.99 4 22 6.01 22 8.5c0 3.78-3.4 6.86-8.55 11.53L12 21.35z'); }
function iconInsights(){ return svgIcon('M15 3l-2 4-4 2 4 2 2 4 2-4 4-2-4-2-2-4zM5 19h4v2H5v-2zm-2-5h2v2H3v-2zm12 6h2v2h-2v-2z'); }

// Spinner SVG used while analyzing
function spinnerSVG(){
  const s = document.createElementNS('http://www.w3.org/2000/svg','svg');
  s.setAttribute('viewBox','0 0 24 24'); s.setAttribute('aria-hidden','true'); s.classList.add('spinner');
  const c = document.createElementNS('http://www.w3.org/2000/svg','circle');
  c.setAttribute('cx','12'); c.setAttribute('cy','12'); c.setAttribute('r','9'); c.setAttribute('fill','none'); c.setAttribute('stroke','currentColor'); c.setAttribute('stroke-width','3'); c.setAttribute('stroke-linecap','round'); c.setAttribute('stroke-dasharray','56'); c.setAttribute('stroke-dashoffset','28');
  s.appendChild(c); return s;
}


// === Map iframe helpers ===
// Resolve when the map iframe fires "load" (with a fallback timeout)
function waitForMapLoad(timeoutMs=4000){
  return new Promise((resolve)=>{
    let done=false, t=null;
    const finish=()=>{ if(done) return; done=true; clearTimeout(t); mapFrame?.removeEventListener('load', finish); setTimeout(resolve, 250); };
    mapFrame?.addEventListener('load', finish);
    t=setTimeout(finish, timeoutMs);
  });
}

// Ask the iframe to export a PNG via postMessage and wait for the reply
function requestMapPng(timeoutMs=5000){
  return new Promise((resolve, reject)=>{
    let done=false, t=null;
    const onMsg=(e)=>{
      const d=e.data||{};
      if(d.type==='EXPORT_MAP_RESULT'){
        window.removeEventListener('message', onMsg);
        done=true; clearTimeout(t);
        if(d.error) reject(new Error(d.error));
        else resolve(d.dataURL);
      }
    };
    window.addEventListener('message', onMsg);
    try{ mapFrame?.contentWindow?.postMessage({type:'EXPORT_MAP'}, '*'); }catch(_){}
    t=setTimeout(()=>{ if(done) return; window.removeEventListener('message', onMsg); reject(new Error('Map export timeout')); }, timeoutMs);
  });
}


// === Route selection state & helpers ===
// Store all returned routes by id
const ROUTES = new Map(); // route_id -> { route_id, kind, name, polyline?, coords? }
let selectedRouteId = null;

// Remember a route object for later selection/analysis
function registerRoute(r) {
  if (!r || !r.route_id) return;
  ROUTES.set(r.route_id, r);
}

// Send a map render request to backend and refresh iframe
async function pushMap(payload) {
  try {
    await fetch('/api/select_route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch (e) {}
  const src = `/static/map.html?ts=${Date.now()}`;
  if (mapFrame) mapFrame.src = src;
}

// Clear the map on backend and refresh iframe
async function clearMap() {
  try {
    await fetch('/api/clear_route', { method: 'POST' });
  } catch (e) {}
  const src = `/static/map.html?ts=${Date.now()}`;
  if (mapFrame) mapFrame.src = src;
}

// Toggle which activity card is selected (and update map)
function updateSelectedUI(activeId) {
  document.querySelectorAll('.activity-box').forEach((box) => {
    const rid = box.getAttribute('data-route-id');
    if (rid && rid === activeId) box.classList.add('selected');
    else box.classList.remove('selected');
  });
}

// Select/deselect a route and render it to the map
function toggleSelect(routeId) {
  if (selectedRouteId === routeId) {
    selectedRouteId = null;
    updateSelectedUI(null);
    clearMap();
    return;
  }
  selectedRouteId = routeId;
  updateSelectedUI(routeId);
  const r = ROUTES.get(routeId);
  if (!r) return;
  if (r.kind === 'generated' && Array.isArray(r.coords)) {
    pushMap({ name: r.name || 'Generated Route', coords: r.coords });
  } else if (r.polyline) {
    pushMap({ name: r.name || 'Activity', polyline: r.polyline });
  } else {
    clearMap();
  }
}


// === Mic recording (speech-to-text) ===
let mediaRecorder = null;
let micChunks = [];
let recording = false;

async function startRecording() {
  // Request mic
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  micChunks = [];
  mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
  mediaRecorder.ondataavailable = (e) => { if (e.data && e.data.size) micChunks.push(e.data); };
  mediaRecorder.start();
  recording = true;
  micBtn?.classList.add('pulsing');
}

function stopTracks(stream) {
  try { stream.getTracks().forEach(t => t.stop()); } catch (_){}
}

async function stopRecordingAndTranscribe() {
  if (!mediaRecorder) return;

  const stream = mediaRecorder.stream;
  const done = new Promise((resolve) => {
    mediaRecorder.onstop = resolve;
  });
  mediaRecorder.stop();
  await done;
  recording = false;
  micBtn?.classList.remove('pulsing');

  // Build a single Blob from chunks
  const blob = new Blob(micChunks, { type: 'audio/webm' });
  stopTracks(stream);

  // Upload to backend for Whisper
  const fd = new FormData();
  fd.append('file', blob, 'input.webm');

  try {
    const res = await fetch('/api/transcribe', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok || !data || typeof data.text !== 'string') {
      throw new Error(data?.error || 'Transcription failed');
    }

    // Put transcript into the input
    const txt = data.text.trim();
    if (txt) {
      input.value = txt;
      updateSendDisabled();
      input.focus();
      // Move cursor to end
      const v = input.value; input.value = ''; input.value = v;
    }
  } catch (e) {
    alert(e.message);
  } finally {
    mediaRecorder = null;
    micChunks = [];
  }
}

// Toggle on click: start if not recording, otherwise stop+transcribe
micBtn?.addEventListener('click', async () => {
  try {
    if (!recording) {
      await startRecording();
    } else {
      await stopRecordingAndTranscribe();
    }
  } catch (e) {
    recording = false;
    micBtn?.classList.remove('pulsing');
    alert(e.message || 'Microphone error');
  }
});


// === Activity card UI ===
// Build a compact card for one activity or generated route
function activityBox(a){
  const rid = a.route_id || '';
  const w = document.createElement('div');
  w.className = 'activity-box';
  if (rid) w.setAttribute('data-route-id', rid);

  // Left: date column
  const date = formatDateOnly(a.start_date);
  const dateCol = document.createElement('div');
  dateCol.className = 'act-date';
  const dTop = document.createElement('div'); dTop.className='act-date-top'; dTop.textContent = date.top;
  const dBot = document.createElement('div'); dBot.className='act-date-bot'; dBot.textContent = date.bottom;
  dateCol.appendChild(dTop); dateCol.appendChild(dBot);

  // Right: metrics and analyze button
  const right = document.createElement('div'); right.className = 'act-right';
  const metrics = document.createElement('div'); metrics.className = 'act-metrics';

  // Build one metric cell with icon + text
  const metric = (iconEl, text) => {
    const m = document.createElement('div'); m.className = 'metric';
    const ic = iconEl; const val = document.createElement('div'); val.className='metric-val'; val.textContent = text;
    m.appendChild(ic); m.appendChild(val); return m;
  };

  // Add all metrics we have
  metrics.appendChild(metric(iconDistance(), formatDistance(a.distance)));
  metrics.appendChild(metric(iconElevation(), formatElevation(a.total_elevation_gain)));
  metrics.appendChild(metric(iconSpeed(), formatPace(a.distance, a.moving_time)));
  metrics.appendChild(metric(iconTime(), formatMovingTime(a.moving_time)));
  metrics.appendChild(metric(iconHeart(), formatHeartRate(a.average_heartrate)));

  // Analyze button
  const analyze = document.createElement('button');
  analyze.className = 'analyze-icon';
  analyze.setAttribute('aria-label', 'Analyze activity');
  analyze.appendChild(iconInsights());

  // Analysis text (populated after LLM call)
  const analysisWrap = document.createElement('div');
  analysisWrap.className = 'act-analysis';
  analysisWrap.textContent = ''; // will fill later

  // Handle analyze click: ensure map is on this route, export PNG, call backend, show result
  analyze.addEventListener('click', async (ev) => {
    ev.stopPropagation();
    analyze.disabled = true;
    const original = analyze.innerHTML;
    analyze.innerHTML = '';
    analyze.appendChild(spinnerSVG());
    analyze.setAttribute('aria-busy','true');

    try{
      // If not selected, select it so the map shows the same route
      const ridNow = w.getAttribute('data-route-id');
      const wasSelected = (selectedRouteId === ridNow);
      if (ridNow && !wasSelected) toggleSelect(ridNow);
      if (!wasSelected) await waitForMapLoad();

      // Ask the iframe to export current map view
      const dataURL = await requestMapPng();

      // Build request payload for the server
      let payload = { name: a.name || 'Activity', image_data_url: dataURL };
      if (a.kind === 'strava') { payload.kind = 'strava'; payload.id = a.id; }
      else { payload.kind = 'generated'; payload.coords = a.coords || []; payload.distance = a.distance; }

      // Call backend to analyze
      const res = await fetch('/api/analyze_activity', {
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'Failed to analyze');

      // Replace button with analysis text
      analyze.remove();
      analysisWrap.textContent = data.analysis || '(no analysis)';
      w.appendChild(analysisWrap);

      // Cache analysis result
      const stored = ROUTES.get(rid) || a;
      stored.analyzed = true; stored.analysis = data.analysis || '';
      ROUTES.set(rid, stored);

    }catch(e){
      // Restore button on failure
      analyze.disabled = false;
      analyze.innerHTML = original;
      analyze.removeAttribute('aria-busy');
      alert(e.message);
      return;
    }
  });

  right.appendChild(metrics);
  right.appendChild(analyze);

  // Build the card DOM
  w.appendChild(dateCol);
  w.appendChild(right);

  // If already analyzed (from earlier), show stored analysis
  if (a.analyzed && a.analysis) {
    analyze.remove();
    analysisWrap.textContent = a.analysis;
    w.appendChild(analysisWrap);
  }

  // Click on card toggles selection + shows route on map
  w.addEventListener('click', () => {
    const id = w.getAttribute('data-route-id'); if (!id) return; toggleSelect(id);
  });

  return w;
}


// === Input state helpers ===
// Enable/disable the Send button based on text and pending state
function updateSendDisabled() {
  const has = input.value.trim().length > 0;
  if (sendBtn) sendBtn.disabled = !has || pending;
}

// Hide the suggestion buttons after first interaction
function hideSuggestions() {
  if (suggestions) {
    suggestions.classList.remove('show');
    suggestions.style.display = 'none';
  }
}


// === Shared send function (form + suggestions) ===
// Handle sending a user message, calling backend, and rendering results
async function sendMessage(userMsg) {
  if (pending || !userMsg) return;
  hideSuggestions();
  pending = true;
  input.value = '';
  input.readOnly = true;
  updateSendDisabled();

  // Add user message and a temporary "Thinking..." bubble
  const userNode = msgBubble(userMsg, 'user'),
    thinking = msgBubble('Thinking...', 'bot');
  out.appendChild(userNode);
  out.appendChild(thinking);

  try {
    // Call backend chat router
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: userMsg }),
    });
    const data = await res.json();
    thinking.remove();

    // Error from server
    if (!res.ok) {
      out.appendChild(msgBubble(`Error: ${data.error || 'Unknown error'}`));
      return;
    }

    // Run mode -> show summary + route cards + map
    if (data.mode === 'run') {
      out.appendChild(msgBubble(data.response || '—', 'bot'));

      // Build activity cards (collapsed to 3 by default)
      if (Array.isArray(data.results) && data.results.length) {
        const group = document.createElement('div');
        group.className = 'activity-group';
        const boxes = data.results.map(r=>{
          registerRoute(r);
          return activityBox(r);
        });

        // Initially show up to 3
        const initial = Math.min(3, boxes.length);
        boxes.forEach((box, i)=>{
          if(i >= initial) box.classList.add('hidden');
          group.appendChild(box);
        });
        out.appendChild(group);

        // "Show all / Hide" toggle if there are more than 3
        if (boxes.length > 3) {
          const toggle = document.createElement('button');
          toggle.className = 'activity-toggle';
          const total = data.count ?? boxes.length;
          const setText = (expanded) => {
            toggle.textContent = expanded ? 'Hide activities' : `Show all ${total} activities`;
            toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
          };
          setText(false);
          toggle.addEventListener('click', ()=>{
            const expanded = toggle.getAttribute('aria-expanded') === 'true';
            if(expanded){
              boxes.forEach((b,i)=>{ if(i>=initial) b.classList.add('hidden'); });
              setText(false);
            }else{
              boxes.forEach((b)=> b.classList.remove('hidden'));
              setText(true);
            }
          });
          out.appendChild(toggle);
        }
      }

      // Auto-select first route if provided, otherwise just refresh map
      if (data.auto_select_route_id) {
        toggleSelect(data.auto_select_route_id);
      } else {
        const src = (data.map || '/static/map.html') + `?ts=${Date.now()}`;
        mapFrame.src = src;
      }
    } else {
      // Plain chat response
      out.appendChild(msgBubble(data.response || '—', 'bot'));
    }

    // Keep scroll at bottom
    out.scrollTop = out.scrollHeight;

  } catch (err) {
    // Network/other errors
    thinking.remove();
    out.appendChild(msgBubble(`Error: ${err.message}`, 'bot'));
  } finally {
    // Reset input state
    pending = false;
    input.readOnly = false;
    updateSendDisabled();
    input.focus();
  }
}


// === Initialize ===
// Disable send when empty
updateSendDisabled();
// Keep button state in sync with input
input.addEventListener('input', updateSendDisabled);

// Show example suggestions only when chat is empty
if (out && out.children.length === 0 && suggestions) {
  suggestions.classList.add('show');
}

// Click on any suggestion sends its text
if (suggestions) {
  suggestions.addEventListener('click', (e) => {
    const btn = e.target.closest('.sugg');
    if (!btn) return;
    const text = btn.getAttribute('data-text') || btn.textContent.trim();
    sendMessage(text);
  });
}


// === Form submit ===
// Send message from the input bar
form.addEventListener('submit', (e) => {
  e.preventDefault();
  const userMsg = input.value.trim();
  if (!userMsg) return;
  sendMessage(userMsg);
});