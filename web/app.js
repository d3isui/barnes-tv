/* Barnes Television Broadcasting System admin UI (no build step, no dependencies). */
// the station's branding (Appearance -> Branding); the page template fills window.BRAND in
const BRAND = Object.assign({ name: "Barnes Television Broadcasting System", short: "Barnes TV", version: "" }, window.BRAND || {});
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const view = $("#view");

function unlockTok() {
  try { const u = JSON.parse(localStorage.getItem("jfb-unlock") || "null"); return u && u.until * 1000 > Date.now() ? u.token : ""; } catch { return ""; }
}
function askLockCode(message) {
  return new Promise((resolve) => {
    const wrap = document.createElement("div");
    wrap.style.cssText = "position:fixed;inset:0;background:#000a;display:grid;place-items:center;z-index:60";
    wrap.innerHTML = `<form class="card" style="width:min(360px,92vw)"><h2>🔒 Channel lock is on</h2>
      <p class="sub">${esc(message || "Enter the lock code to make changes.")}</p>
      <input type="password" inputmode="numeric" autocomplete="off" placeholder="Lock code" style="width:100%;font-size:20px;letter-spacing:.3em">
      <p class="sub" id="lk-err" style="color:var(--red);min-height:18px"></p>
      <div class="row"><span class="spacer"></span><button type="button" class="btn" id="lk-cancel">Cancel</button><button class="btn primary">Unlock</button></div></form>`;
    document.body.appendChild(wrap);
    const input = $("input", wrap); input.focus();
    $("#lk-cancel", wrap).onclick = () => { wrap.remove(); resolve(false); };
    $("form", wrap).onsubmit = async (e) => {
      e.preventDefault();
      const r = await fetch("/api/lock/unlock", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: input.value }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { $("#lk-err", wrap).textContent = d.error || "Wrong code"; input.value = ""; input.focus(); return; }
      try { localStorage.setItem("jfb-unlock", JSON.stringify({ token: d.token, until: d.until })); } catch { }
      wrap.remove(); resolve(true);
    };
  });
}
async function api(method, path, body, raw, retried) {
  const opt = { method, headers: {} };
  if (unlockTok()) opt.headers["X-Unlock"] = unlockTok();
  if (raw) { opt.body = raw; opt.headers["Content-Type"] = raw.type || "application/octet-stream"; }
  else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
  const r = await fetch("/api/" + path, opt);
  const txt = await r.text();
  let data; try { data = JSON.parse(txt); } catch { data = txt; }
  if (r.status === 403 && data && data.locked && !retried && method !== "GET") {
    if (await askLockCode(data.error)) return api(method, path, body, raw, true);
  }
  if (!r.ok) throw new Error((data && data.error) || txt || r.statusText);
  return data;
}
function fmtLen(sec) {
  sec = Math.round(sec || 0);
  return sec >= 60 ? `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}` : `${sec}s`;
}
function toast(msg, err) {
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), err ? 7000 : 3000);
}
const fmtTime = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const fmtDay = (t) => new Date(t * 1000).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Copied"); }
  catch { prompt("Copy this:", text); }
}

const SOURCE_TYPES = [["library", "Library"], ["genre", "Genre"], ["collection", "Collection"], ["series", "Series"],
  ["playlist", "Playlist"], ["tag", "Tag"], ["studio", "Studio / Network"]];
const ORDERS = {
  shuffle: "Shuffle — everything plays once before anything repeats",
  series_rotation: "Rotate shows — random show each slot, episodes in order (classic reruns)",
  sequential: "In order — by series/season/episode or release date, then loop",
  random: "Pure random — anything can play next",
};
const LANGS = [["", "Default track"], ["eng", "English"], ["jpn", "Japanese"], ["spa", "Spanish"], ["fre", "French"],
  ["ger", "German"], ["ita", "Italian"], ["por", "Portuguese"], ["kor", "Korean"], ["chi", "Chinese"], ["rus", "Russian"], ["hin", "Hindi"]];

// ---------------------------------------------------------------- themes & fonts
let THEMES = null;
async function loadThemes(force) {
  if (!THEMES || force) THEMES = await api("GET", "themes");
  return THEMES;
}
const themeName = (id) => (THEMES?.themes.find((t) => t.id === id) || {}).name || id;
const fontInfo = (id) => (THEMES?.fonts || []).find((f) => f.id === id) || { name: id, css: "inherit" };
const fontCss = (id) => fontInfo(id).css;
// a <select> of fonts. themeFont = the font "theme" stands for (shown in the first option)
function fontOptions(value, themeFont, { clock = false, themeLabel = "Theme default", noSystem = false } = {}) {
  const fonts = (THEMES?.fonts || []).filter((f) => (clock || f.kind !== "clock") && !(noSystem && f.id === "system"));
  const group = (label, list) => list.length ? `<optgroup label="${label}">${list.map((f) =>
    `<option value="${esc(f.id)}" ${value === f.id ? "selected" : ""}>${esc(f.name)}</option>`).join("")}</optgroup>` : "";
  return (themeFont !== undefined ? `<option value="theme" ${!value || value === "theme" ? "selected" : ""}>${themeLabel} (${esc(fontInfo(themeFont).name)})</option>` : "")
    + group("Clock faces", fonts.filter((f) => f.kind === "clock"))
    + group("Display", fonts.filter((f) => f.kind === "display"))
    + group("Text", fonts.filter((f) => f.kind === "text"))
    + group("Your fonts", fonts.filter((f) => f.custom));
}
function resolveFont(value, themeFont) { return !value || value === "theme" ? themeFont : value; }
function sampleFont(el, fontId, text) {
  if (!el) return;
  el.style.fontFamily = fontCss(fontId);
  if (text !== undefined) el.textContent = text;
  const f = fontInfo(fontId); el.title = f.desc || "";
}
function clockSample(fmt) {
  const d = new Date(); let h = d.getHours(); const m = String(d.getMinutes()).padStart(2, "0"), sec = String(d.getSeconds()).padStart(2, "0");
  if (fmt === "24h") return `${String(h).padStart(2, "0")}:${m}`;
  if (fmt === "24h_sec") return `${String(h).padStart(2, "0")}:${m}:${sec}`;
  const ap = h >= 12 ? "PM" : "AM"; h = h % 12 || 12;
  if (fmt === "12h_plain") return `${h}:${m}`;
  if (fmt === "12h_sec") return `${h}:${m}:${sec} ${ap}`;
  return `${h}:${m} ${ap}`;
}
const CLOCK_PRESETS = {
  classic: { label: "Classic", font: "theme", outline: "none", shadow: true, bg_opacity: 35, opacity: 100, color: "#ffffff", format: "12h" },
  japan: { label: "🇯🇵 Japanese broadcast", font: "maru", outline: "thick", shadow: true, bg_opacity: 0, opacity: 100, color: "#ffffff", format: "12h_plain", size_percent: 5.5 },
  vcr: { label: "📼 VCR", font: "dseg7", outline: "none", shadow: false, bg_opacity: 70, opacity: 92, color: "#5cffb0", format: "24h" },
  news: { label: "📰 News ticker", font: "bebas", outline: "none", shadow: false, bg_opacity: 85, opacity: 100, color: "#ffffff", format: "12h" },
  teletext: { label: "📟 Teletext", font: "vt323", outline: "none", shadow: false, bg_opacity: 100, opacity: 100, color: "#ffff00", format: "24h_sec" },
  neon: { label: "💜 Neon", font: "audiowide", outline: "thin", shadow: true, bg_opacity: 0, opacity: 100, color: "#ff4fa3", format: "12h" },
  ghost: { label: "👻 Subtle", font: "inter", outline: "thin", shadow: false, bg_opacity: 0, opacity: 55, color: "#ffffff", format: "12h_plain" },
};

let STATUS = null;
async function loadStatus() {
  try { STATUS = await api("GET", "status"); } catch (e) { STATUS = null; }
  if (STATUS) $("#ver").textContent = "v" + STATUS.version;
  if (STATUS && STATUS.brand) { Object.assign(BRAND, STATUS.brand); $("#station").textContent = BRAND.name; }
  return STATUS;
}

// --------------------------------------------------------------------------- router
const routes = { channels: showChannels, channel: showChannel, guide: showGuide, settings: showSettings, connect: showConnect, appearance: showAppearance, theme: showThemeBuilder,
  bumpers: showBumpers, bumper: showBumper };
let timer = null, leaveGuard = null, prevHash = location.hash, skipRoute = false;
async function route() {
  if (skipRoute) { skipRoute = false; return; }
  if (leaveGuard && location.hash !== prevHash && !leaveGuard()) { skipRoute = true; location.hash = prevHash; return; }
  leaveGuard = null; prevHash = location.hash;
  clearInterval(timer);
  const [name, arg] = location.hash.replace(/^#\//, "").split("/");
  const fn = routes[name] || showChannels;
  const navName = name === "channel" ? "channels" : name === "bumper" ? "bumpers" : name === "theme" ? "appearance" : name || "channels";
  $$("nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === navName));
  view.innerHTML = '<p class="muted">Loading…</p>';
  try { await fn(arg); } catch (e) { view.innerHTML = `<div class="card"><h2>Something went wrong</h2><p>${esc(e.message)}</p></div>`; }
}
window.addEventListener("hashchange", route);
window.addEventListener("beforeunload", (e) => { if (leaveGuard && !leaveGuard(true)) { e.preventDefault(); e.returnValue = ""; } });

// --------------------------------------------------------------------------- channels list
async function showChannels() {
  const st = await loadStatus();
  if (st && !st.configured) {
    view.innerHTML = `<div class="card empty"><img class="brandart" src="/brand/wordmark.png?v=${BRAND.version}" alt="${esc(BRAND.name)}" style="width:min(460px,80%);margin:0 auto 18px;display:block">
      <h1>Welcome to ${esc(BRAND.name)}</h1>
      <p>First, connect to your Jellyfin server.</p><a class="btn primary" href="#/settings">Open Settings</a></div>`;
    return;
  }
  const render = async () => {
    const chans = await api("GET", "channels");
    view.innerHTML = `<div class="row" style="margin-bottom:16px"><h1 style="margin:0">Channels</h1><span class="spacer"></span>
      <button class="btn primary" id="new">+ New channel</button></div>
      <div class="grid">${chans.map(card).join("")}</div>`;
    $("#new").onclick = async () => {
      const ch = await api("POST", "channels", { name: "New Channel" });
      location.hash = "#/channel/" + ch.id;
    };
    $$("[data-copy]").forEach((b) => (b.onclick = () => copy(b.dataset.copy)));
    $$("[data-cast]").forEach((b) => (b.onclick = () => castDialog(b.dataset.cast, b.dataset.name)));
  };
  await render();
  timer = setInterval(() => { if (!document.hidden && !$("input:focus")) render(); }, 15000);
}

function card(c) {
  const now = c.now, nx = c.next;
  const pct = now ? Math.min(100, Math.max(0, ((Date.now() / 1000 - now.start) / (now.end - now.start)) * 100)) : 0;
  const live = c.session && c.session.viewers > 0;
  let body;
  if (c.type === "guide") body = `<div class="sub">Scrolling program guide for every channel${c.music_path ? " with music" : ""}.</div>`;
  if (c.type === "weather") body = `<div class="now">🌤 ${esc(c.now ? c.now.subtitle : "Local weather")}</div><div class="sub">Forecast, radar and alerts${c.music_path ? " with music" : ""}.</div>`;
  else if (now) body = `<div><div class="now">${esc(now.title)}</div><div class="sub">${esc(now.subtitle || "")}</div></div>
      <div class="progress"><div style="width:${pct}%"></div></div>
      <div class="sub">${fmtTime(now.start)} – ${fmtTime(now.end)}${nx ? ` · Next: <b>${esc(nx.title)}</b> at ${fmtTime(nx.start)}` : ""}</div>`;
  else body = `<div class="sub">${esc(c.error || "No schedule yet — add sources.")}</div>`;
  const pool = c.pool ? `<span class="sub">${c.pool.items} items · ${c.pool.hours} h${c.pool.fillers ? ` · ${c.pool.fillers} fillers` : ""}</span>` : "";
  return `<div class="card chan">
    <div class="head"><img class="logo" src="${c.logo_url}" alt=""><span class="num">${esc(c.number)}</span>
      <div style="flex:1;min-width:0"><div class="name">${esc(c.name)}</div>
      <div class="row" style="gap:6px">${c.type === "guide" ? '<span class="badge">Guide</span>' : c.type === "weather" ? '<span class="badge">Weather</span>' : ""}
      ${c.kids ? '<span class="badge" style="color:var(--green);border-color:var(--green)">🧸 Kids</span>' : c.locked ? '<span class="badge">🔒 Locked</span>' : ""}
      ${c.enabled ? "" : '<span class="badge off">Off</span>'}${live ? `<span class="badge live">● ${c.session.viewers} watching</span>` : ""}${pool}</div></div></div>
    ${c.session && c.session.speed && c.session.speed < 0.95 ? `<div class="sub" style="color:var(--red)">⚠ Encoding at only ${c.session.speed}× real time — viewers will buffer. Try a faster preset, 720p, or a GPU encoder in Settings.</div>` : ""}
    ${body}
    ${c.pool && c.pool.error ? `<div class="sub" style="color:var(--red)">${esc(c.pool.error)}</div>` : ""}
    <div class="row"><a class="btn small" href="#/channel/${c.id}">Edit</a>
      <a class="btn small" href="/tv#${encodeURIComponent(c.number)}" target="_blank">Watch</a>
      <button class="btn small" data-cast="${c.id}" data-name="${esc(c.number + " " + c.name)}">Cast…</button>
      <button class="btn small" data-copy="${esc(c.stream_url)}">Copy stream URL</button></div>
  </div>`;
}

// --------------------------------------------------------------------------- casting
async function castDialog(channelId, label) {
  const wrap = document.createElement("div");
  wrap.style.cssText = "position:fixed;inset:0;background:#000a;display:grid;place-items:center;z-index:50";
  wrap.innerHTML = `<div class="card" style="width:min(460px,92vw)"><h2>Cast ${esc(label)}</h2>
    <p class="sub" id="cd-hint">Looking for Chromecasts…</p><div id="cd-list" class="stack" style="gap:8px"></div>
    <div class="row" style="margin-top:14px"><span class="spacer"></span><button class="btn" id="cd-close">Close</button></div></div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
  $("#cd-close", wrap).onclick = close;
  let d;
  try { d = await api("GET", "cast/devices"); } catch (e) { $("#cd-hint", wrap).textContent = e.message; return; }
  if (!d.available) { $("#cd-hint", wrap).textContent = d.error; return; }
  $("#cd-hint", wrap).innerHTML = d.devices.length ? `Streams from <code>${esc(d.base_url)}</code>` :
    "No Chromecasts found yet. Check that the TV is on and on the same network, or add its IP under Settings → Chromecast.";
  $("#cd-list", wrap).innerHTML = d.devices.map((x) => `<div class="row"><b style="flex:1">📺 ${esc(x.name)} <span class="sub">${esc(x.model)}</span></b>
      ${x.channel ? `<button class="btn small" data-stop="${esc(x.id)}">Stop</button>` : ""}
      <button class="btn small primary" data-play="${esc(x.id)}">Cast here</button></div>`).join("");
  $$("[data-play]", wrap).forEach((b) => (b.onclick = async () => {
    b.disabled = true; b.textContent = "Starting…";
    try { await api("POST", "cast/play", { device: b.dataset.play, channel: channelId }); toast("Casting — the TV should start in a few seconds"); close(); }
    catch (e) { toast(e.message, true); b.disabled = false; b.textContent = "Cast here"; }
  }));
  $$("[data-stop]", wrap).forEach((b) => (b.onclick = async () => { await api("POST", "cast/stop", { device: b.dataset.stop }); toast("Stopped"); close(); }));
}

// --------------------------------------------------------------------------- channel editor
function cornerPicker(id, value) {
  return `<div class="corners" data-corner="${id}">${["top-left", "top-right", "bottom-left", "bottom-right"]
    .map((p) => `<button type="button" title="${p}" data-pos="${p}" class="${p === value ? "on" : ""}"></button>`).join("")}</div>`;
}
function sourcePicker(id, title, help) {
  return `<div class="wide"><h3>${title}</h3>${help ? `<p class="sub" style="margin-top:-4px">${help}</p>` : ""}
    <div class="chips" id="${id}-chips"></div>
    <div class="searchbox" style="margin-top:8px">
      <select id="${id}-type">${SOURCE_TYPES.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>
      <input type="text" id="${id}-q" placeholder="Filter…" style="width:140px">
      <select id="${id}-list" class="big"><option value="">Choose…</option></select>
      <button type="button" class="btn small" id="${id}-add">Add</button>
    </div></div>`;
}
function wireSourcePicker(id, list, onChange = () => { }) {
  const chips = $(`#${id}-chips`), type = $(`#${id}-type`), q = $(`#${id}-q`), sel = $(`#${id}-list`);
  const draw = () => {
    chips.innerHTML = list.length ? list.map((s, i) => `<span class="chip"><b>${esc(s.type)}</b>${esc(s.name)}<button type="button" data-i="${i}">×</button></span>`).join("")
      : '<span class="sub">None</span>';
    $$("button", chips).forEach((b) => (b.onclick = () => { list.splice(+b.dataset.i, 1); draw(); onChange(); }));
  };
  let cache = {};
  const load = async () => {
    const key = type.value + "|" + q.value;
    sel.innerHTML = "<option>Loading…</option>";
    try {
      cache[key] = cache[key] || (await api("GET", `jellyfin/sources?type=${type.value}&q=${encodeURIComponent(q.value)}`));
      sel.innerHTML = `<option value="">Choose ${type.selectedOptions[0].text.toLowerCase()}… (${cache[key].length})</option>` +
        cache[key].map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("");
    } catch (e) { sel.innerHTML = `<option value="">${esc(e.message)}</option>`; }
  };
  type.onchange = load;
  let deb; q.oninput = () => { clearTimeout(deb); deb = setTimeout(load, 350); };
  $(`#${id}-add`).onclick = () => {
    if (!sel.value) return;
    const name = sel.selectedOptions[0].text;
    if (!list.some((s) => s.type === type.value && s.id === sel.value)) list.push({ type: type.value, id: sel.value, name });
    draw(); onChange();
  };
  draw(); load();
}

async function showChannel(id) {
  const [ch, TH] = await Promise.all([api("GET", "channels/" + id), loadThemes()]);
  const stationTheme = TH.current || "barnes";
  const chTheme = () => TH.themes.find((t) => t.id === ($("#theme")?.value || stationTheme)) || TH.themes[0];
  const weather = ch.type === "weather";
  const guide = ch.type === "guide" || weather;      // channels drawn live instead of playing a schedule
  const WX = ch.weather || {}, WXL = WX.location || {};
  const WX_SLIDES = [["current", "Current conditions"], ["hourly", "Next 12 hours"], ["daily", "7-day forecast"], ["radar_local", "Local radar"],
    ["radar_regional", "Regional radar"], ["radar_future", "Future radar (forecast, US only)"], ["almanac", "Sun & moon"], ["alerts", "Weather alerts (only when there are any)"]];
  const sources = [...(ch.sources || [])], exclude = [...(ch.exclude || [])], fillers = [...(ch.filler_sources || [])];
  const slots = (ch.slots || []).map((s) => ({ ...s, sources: [...(s.sources || [])], days: [...(s.days || [])] }));
  const logo = ch.logo || {}, clock = ch.clock || {}, un = ch.up_next || {}, hl = ch.header_logo || {};
  const HL_MODES = [["station", `Station logo (${esc(BRAND.short)})`], ["channel", "This channel's logo"], ["custom", "A different image…"],
    ["name", "Station name as text"], ["none", "Nothing"]];
  const br = ch.breaks || {}, bu = ch.bumpers || {}, sub = ch.subtitles || {};
  const brSources = [...(br.sources || [])], buSources = [...(bu.sources || [])];
  view.innerHTML = `
  <div class="row" style="margin-bottom:16px"><a href="#/channels" class="btn small">← Channels</a>
    <h1 style="margin:0">${esc(ch.number)} · ${esc(ch.name)}</h1><span class="spacer"></span>
    <a class="btn" href="/tv#${encodeURIComponent(ch.number)}" target="_blank">▶ Watch</a>
    <button class="btn" id="castbtn">Cast…</button>
    <span class="sub" id="unsaved" style="display:none;color:var(--accent)">Unsaved changes</span>
    <button class="btn primary" id="save">Save</button></div>
  <div class="editor">
   <div class="stack">
    <div class="card"><h2>Channel</h2><div class="form">
      <label class="f">Name<input type="text" id="name" value="${esc(ch.name)}"></label>
      <label class="f">Number<input type="number" id="number" step="0.1" value="${esc(ch.number)}"></label>
      <label class="f">Group (shown in Jellyfin)<input type="text" id="group" value="${esc(ch.group || "")}" placeholder="e.g. Kids"></label>
      <label class="f">Type<select id="type"><option value="standard">Regular channel</option><option value="guide" ${ch.type === "guide" ? "selected" : ""}>Guide channel</option><option value="weather" ${weather ? "selected" : ""}>Weather channel</option></select></label>
      <label class="check"><input type="checkbox" id="enabled" ${ch.enabled ? "checked" : ""}> On the air</label>
      <label class="check wide"><input type="checkbox" id="kids" ${ch.kids ? "checked" : ""}> 🧸 Kids channel: always watchable, even when the channel lock is on</label>
      ${guide ? "" : `<label class="f wide">🌙 Sleep channel: turn the screen off by itself (picture goes black, sound keeps playing)
        <select id="screen_off">${[[0, "Never"], [1, "After 1 minute"], [2, "After 2 minutes"], [5, "After 5 minutes"], [10, "After 10 minutes"], [15, "After 15 minutes"], [30, "After 30 minutes"]]
          .map(([v, l]) => `<option value="${v}" ${(+ch.screen_off_minutes || 0) === v ? "selected" : ""}>${l}</option>`).join("")}</select>
        <span class="sub">Counts from when you tune in or last press a button, on the TV page and the TV app. Any button brings the picture back.</span></label>`}
      <label class="f wide">Theme ${weather ? "(the whole weather channel)" : guide ? "(the whole guide channel)" : "(Up Next / standby cards, Up Next banner, default clock font)"}
        <select id="theme"><option value="">Station theme (${esc(themeName(stationTheme))})</option>
        ${TH.themes.map((t) => `<option value="${t.id}" ${ch.theme === t.id ? "selected" : ""}>${esc(t.name)}</option>`).join("")}</select></label>
    </div></div>
    ${weather ? `<div class="card"><h2>🌤 Weather channel</h2><div class="form">
      <label class="f">Location<select id="wx_mode">${[["auto", "Automatic (from your internet connection)"], ["zip", "ZIP / postal code"], ["city", "City name"], ["coords", "Exact coordinates"]]
        .map(([v, l]) => `<option value="${v}" ${(WXL.mode || "auto") === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="f wxm" data-m="zip">ZIP / postal code<input type="text" id="wx_zip" value="${esc(WXL.zip || "")}" placeholder="62701"></label>
      <label class="f wxm" data-m="zip">Country (2-letter code)<input type="text" id="wx_country" maxlength="2" value="${esc(WXL.country || "US")}"></label>
      <label class="f wxm" data-m="city">City<input type="text" id="wx_query" value="${esc(WXL.query || "")}" placeholder="Springfield, Illinois"></label>
      <label class="f wxm" data-m="coords">Latitude<input type="text" id="wx_lat" value="${esc(WXL.lat ?? "")}" placeholder="39.80"></label>
      <label class="f wxm" data-m="coords">Longitude<input type="text" id="wx_lon" value="${esc(WXL.lon ?? "")}" placeholder="-89.65"></label>
      <label class="f">Name shown on screen (optional)<input type="text" id="wx_name" value="${esc(WXL.name || "")}" placeholder="automatic"></label>
      <div class="wide row"><button class="btn small" id="wx_check">📍 Check location &amp; weather</button><span class="sub" id="wx_result">Save first if you changed the location.</span></div>
      <label class="f">Units<select id="wx_units">${[["auto", "Automatic (°F in the US)"], ["imperial", "°F, mph, inches"], ["metric", "°C, km/h, hPa"]]
        .map(([v, l]) => `<option value="${v}" ${(WX.units || "auto") === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="f">Clock format<select id="guide_clock_fmt">${Object.entries(TH.clock_formats).map(([k, v]) => `<option value="${k}" ${(clock.format || "12h") === k ? "selected" : ""}>${{"12h": "12-hour", "12h_plain": "12-hour, no AM/PM", "12h_sec": "12-hour with seconds", "24h": "24-hour", "24h_sec": "24-hour with seconds"}[k]} (${v})</option>`).join("")}</select></label>
      <div class="wide"><h3>Screens, in order</h3><div class="row">${WX_SLIDES.map(([k, l]) =>
        `<label class="check"><input type="checkbox" data-wxslide="${k}" ${(WX.slides || WX_SLIDES.map((x) => x[0])).includes(k) ? "checked" : ""}> ${l}</label>`).join("")}</div></div>
      <label class="f">Seconds per screen<input type="number" id="wx_secs" min="5" max="60" value="${WX.slide_seconds || 10}"></label>
      <label class="f">Radar loop length<select id="wx_frames">${[3, 6, 9, 12].map((n) => `<option value="${n}" ${(WX.radar_frames || 6) === n ? "selected" : ""}>${n * 10} minutes</option>`).join("")}</select></label>
      <label class="f">Radar: hide weak echoes (US)<select id="wx_mindbz">${[["all", "Show everything (raw, incl. clear-air static)"], [5, "Below 5 dBZ"],
        [10, "Below 10 dBZ (recommended)"], [15, "Below 15 dBZ"], [20, "Below 20 dBZ (rain only)"]].map(([v, l]) =>
        `<option value="${v}" ${String(WX.radar_min_dbz ?? 10) === String(v) ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="check"><input type="checkbox" id="wx_alerts" ${WX.alerts !== false ? "checked" : ""}> Severe weather alerts (US)</label>
      <label class="check"><input type="checkbox" id="wx_crawl" ${WX.crawl !== false ? "checked" : ""}> Scrolling crawl along the bottom</label>
      <label class="f">Crawl speed<input type="range" id="wx_speed" min="40" max="250" value="${WX.crawl_speed || 110}"></label>
      <label class="f wide">Background music (file or folder on the Broadcast server)<input type="text" id="music_path" value="${esc(ch.music_path || "")}" placeholder="D:\\Music\\Smooth Jazz"></label>
      <label class="f">Text font<select id="guide_font">${fontOptions(ch.guide_font, chTheme().fonts.guide)}</select></label>
      <label class="f">Big numbers &amp; headings font<select id="guide_display_font">${fontOptions(ch.guide_display_font, chTheme().fonts.guide_display)}</select></label>
      <div class="fontsample wide" id="guide_sample">72° Partly Cloudy · High 75° · Low 58°</div>
    </div><p class="sub">Forecasts from Open-Meteo, alerts from the US National Weather Service, radar from RainViewer, maps © OpenStreetMap contributors / CARTO.
      Free for personal use, no accounts or keys. The channel keeps showing the last good forecast if the internet drops.</p></div>` : guide ? `<div class="card"><h2>Guide channel</h2><div class="form">
      <label class="f wide">Background music (file or folder on the Broadcast server)<input type="text" id="music_path" value="${esc(ch.music_path || "")}" placeholder="D:\\Music\\Smooth Jazz"></label>
      <label class="f">Scroll speed<input type="range" id="guide_scroll_speed" min="10" max="120" value="${ch.guide_scroll_speed || 40}"></label>
      <label class="f">Clock format<select id="guide_clock_fmt">${Object.entries(TH.clock_formats).map(([k, v]) => `<option value="${k}" ${(clock.format || "12h") === k ? "selected" : ""}>${{"12h": "12-hour", "12h_plain": "12-hour, no AM/PM", "12h_sec": "12-hour with seconds", "24h": "24-hour", "24h_sec": "24-hour with seconds"}[k]} (${v})</option>`).join("")}</select></label>
      <label class="f">Listings font<select id="guide_font">${fontOptions(ch.guide_font, chTheme().fonts.guide)}</select></label>
      <label class="f">Clock &amp; channel numbers font<select id="guide_display_font">${fontOptions(ch.guide_display_font, chTheme().fonts.guide_display)}</select></label>
      <div class="fontsample wide" id="guide_sample">Tokyo Night Drive · となりのアニメ</div>
    </div><p class="sub">The guide lists every regular channel that's on the air, with a spotlight on what's playing now.</p></div>` : `
    <div class="card"><h2>Programming</h2><div class="form">
      ${sourcePicker("src", "What plays on this channel", "Mix and match libraries, genres, collections, single shows, playlists, tags or studios/networks.")}
      ${sourcePicker("exc", "Never play", "Optional: anything matching these is removed (e.g. exclude the Horror genre from a kids channel).")}
      <div class="wide"><h3>Item types</h3><div class="row">${["Movie", "Episode", "MusicVideo", "Video"].map((t) =>
        `<label class="check"><input type="checkbox" data-itype="${t}" ${(ch.item_types || []).includes(t) ? "checked" : ""}> ${t === "MusicVideo" ? "Music videos" : t === "Video" ? "Home videos" : t + "s"}</label>`).join("")}
        <label class="check"><input type="checkbox" id="include_specials" ${ch.include_specials ? "checked" : ""}> Include specials (season 0)</label></div></div>
      <label class="f">Shortest item (minutes, 0 = any)<input type="number" id="min_minutes" min="0" value="${ch.min_minutes || 0}"></label>
      <label class="f">Longest item (minutes, 0 = any)<input type="number" id="max_minutes" min="0" value="${ch.max_minutes || 0}"></label>
      <label class="f wide">Order<select id="order">${Object.entries(ORDERS).map(([k, v]) => `<option value="${k}" ${ch.order === k ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <label class="check wide"><input type="checkbox" id="no_repeat_show" ${ch.no_repeat_show !== false ? "checked" : ""}> Never play the same show twice in a row
        <span class="sub">(another show always airs in between, when the channel has more than one)</span></label>
      <label class="f">Start times<select id="padding_minutes">${[[0, "Back-to-back"], [15, "On the quarter hour"], [30, "On the half hour (:00 / :30)"], [60, "On the hour"]]
        .map(([v, l]) => `<option value="${v}" ${+ch.padding_minutes === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="f">Audio language<select id="audio_language">${LANGS.map(([v, l]) => `<option value="${v}" ${ch.audio_language === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="check"><input type="checkbox" id="normalize_audio" ${ch.normalize_audio ? "checked" : ""}> Even out loudness</label>
      ${sourcePicker("fil", "Filler for the gaps", "When shows start on the hour/half hour, gaps are filled with these (commercials, music videos, shorts ≤ 15 min). Anything left over shows an “Up Next” card.")}
      <label class="f wide">Music under “Up Next” cards (file or folder on the Broadcast server, optional)<input type="text" id="music_path" value="${esc(ch.music_path || "")}"></label>
    </div></div>
    <div class="card" id="slotcard"><h2>📅 Time slots</h2>
      <p class="sub" style="margin-top:0">Shows, movies or collections that air at set times, like “The Simpsons, Mon–Fri 8–9 PM” or
        “a movie every Friday at 8”. Regular programming fills the rest of the day. Changes apply when you save.</p>
      <div id="slotlist"></div>
      <div id="sloted" class="slotedit" style="display:none"></div>
      <div class="row" style="margin-top:8px"><button class="btn" id="slot_add">+ Add a time slot</button></div></div>
    <div class="card" id="poolcard"><h2>📊 What's on this channel</h2>
      <div class="row"><div class="seg" id="pool_mode">${[["items", "Items"], ["hours", "Hours"], ["plan", "Airtime goal"], ["sched", "Scheduled"]]
        .map(([k, l]) => `<button class="btn small" data-pm="${k}">${l}</button>`).join("")}</div><span class="spacer"></span><span class="sub" id="pool_total">Loading…</span></div>
      <div class="poolwrap"><svg id="pool_pie" viewBox="-110 -110 220 220" aria-label="Pool breakdown"></svg><div id="pool_legend"></div></div>
      <h3>Balance the airtime</h3>
      <p class="sub" style="margin-top:0">Off by default: every episode and movie gets its turn, so a show with 300 episodes airs far more than one with 10.
        Slide right to even things out, or give single shows more or less time with their own sliders. Saving rebuilds the schedule after what's on now.</p>
      <div class="form"><label class="f wide">Even out the shows: <b id="bal_val"></b>
        <input type="range" id="bal_strength" min="0" max="100" step="5" value="${+((ch.balance || {}).strength) || 0}">
        <span class="row sub" style="justify-content:space-between"><span>Off (as the pool is)</span><span>Equal time for every show</span></span></label></div>
      <div class="row"><button class="btn small" id="bal_reset">Reset balancing</button><span class="sub" id="bal_note"></span></div></div>
    <div class="card"><h2>Subtitles</h2>
      <div class="form">
        <label class="f wide">Show subtitles<select id="sub_mode">${[["off", "Off"], ["always", "Always, when the show has them"],
          ["foreign", "Only when the audio isn't in my language (e.g. Japanese audio → English subtitles)"],
          ["forced", "Only “forced” subtitles (signs, songs and foreign-language lines)"]].map(([v, l]) =>
          `<option value="${v}" ${(sub.mode || "off") === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="f">Subtitle language<select id="sub_lang">${LANGS.filter(([v]) => v).map(([v, l]) => `<option value="${v}" ${(sub.language || "eng") === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="f">Size<select id="sub_size">${["small", "medium", "large", "huge"].map((x) => `<option ${(sub.size || "medium") === x ? "selected" : ""}>${x}</option>`).join("")}</select></label>
        <label class="f">Font (plain-text subtitles)<select id="sub_font"><option value="">Standard</option>${fontOptions(sub.font || "", undefined, { noSystem: true })}</select></label>
        <label class="f">Look<select id="sub_style"><option value="outline">White with black outline</option><option value="box" ${sub.style === "box" ? "selected" : ""}>On a dark box</option></select></label>
        <label class="check wide"><input type="checkbox" id="sub_prog" ${sub.programs_only !== false ? "checked" : ""}> Shows and movies only (no subtitles on commercials and filler)</label>
      </div>
      <div class="row" style="margin-top:10px"><button class="btn small" id="sub_check">🔍 Check subtitles on what's on now</button>
        <span class="sub">Save first if you changed anything.</span></div>
      <div id="sub_result" class="sub" style="margin-top:8px"></div>
      <p class="sub">Subtitles are drawn into the picture, so they show on every TV, browser and Chromecast. Text subtitles (SRT, ASS) and
        Blu-ray/DVD picture subtitles both work; styled anime (ASS) subtitles keep their own fonts and colours. Japanese, Chinese and Korean
        subtitles automatically use a font that has those characters.</p></div>
    <div class="card"><h2>Commercial breaks</h2>
      <label class="check"><input type="checkbox" id="br_on" ${br.enabled ? "checked" : ""}> Interrupt shows with commercial breaks, then pick up right where they left off</label>
      <div class="form" style="margin-top:12px">
        ${sourcePicker("brk", "Commercials come from", "Make a library in Jellyfin (e.g. “Commercials”, Home Videos type) full of short clips and pick it here.")}
        <label class="f">Minutes of show between breaks<input type="number" id="br_interval" min="1" step="0.5" value="${br.interval_minutes ?? 8}"></label>
        <label class="f">Break length (seconds)<input type="number" id="br_len" min="5" step="5" value="${br.length_seconds ?? 120}"></label>
        <label class="f">No breaks in the last … minutes<input type="number" id="br_tail" min="0" step="0.5" value="${br.min_tail_minutes ?? 3}"></label>
        <label class="f">Max breaks per show (0 = no limit)<input type="number" id="br_max" min="0" value="${br.max_per_program || 0}"></label>
        <div class="wide row">
          <label class="check"><input type="checkbox" id="br_eps" ${br.episodes !== false ? "checked" : ""}> During episodes</label>
          <label class="check"><input type="checkbox" id="br_movies" ${br.movies !== false ? "checked" : ""}> During movies</label>
          <label class="check"><input type="checkbox" id="br_ch" ${br.use_chapters !== false ? "checked" : ""}> Snap to chapter marks (act breaks) when the file has them</label>
          <label class="check"><input type="checkbox" id="br_gfx" ${br.show_graphics ? "checked" : ""}> Keep logo &amp; clock on commercials</label></div>
        <label class="check wide"><input type="checkbox" id="br_split" ${br.split !== false ? "checked" : ""}> Find the separate ads inside long commercial videos (compilations)</label>
        <label class="f">…in videos longer than (seconds)<input type="number" id="br_split_over" min="20" step="10" value="${br.split_over_seconds ?? 90}"></label>
        <div class="wide" id="br_comp"></div>
      </div>
      <p class="sub">Breaks are filled with whole commercials up to the length you set. The guide still lists each show as one block, like real TV.</p></div>
    <div class="card"><h2>Bumpers</h2>
      <label class="check"><input type="checkbox" id="bu_on" ${bu.enabled ? "checked" : ""}> Play bumpers</label>
      <div class="row" style="margin-top:10px">
        <label class="check"><input type="checkbox" id="bu_into" ${bu.into_break !== false ? "checked" : ""}> Going into a break</label>
        <label class="check"><input type="checkbox" id="bu_out" ${bu.out_of_break !== false ? "checked" : ""}> Coming back from a break</label>
        <label class="check"><input type="checkbox" id="bu_between" ${bu.between_programs !== false ? "checked" : ""}> Between shows (“next: …”)</label>
        <label class="check"><input type="checkbox" id="bu_gfx" ${bu.show_graphics ? "checked" : ""}> Keep logo &amp; clock on bumpers</label></div>
      <div class="form" style="margin-top:10px"><label class="f">Bumpers around commercial breaks<select id="bu_every">${[[1, "Every break"], [2, "Every 2nd break"], [3, "Every 3rd break"], [4, "Every 4th break"]].map(([v, l]) => `<option value="${v}" ${(bu.every_breaks || 1) === v ? "selected" : ""}>${l}</option>`).join("")}</select></label></div>
      <h3>Text bumpers to use <a href="#/bumpers" style="font-size:12px;text-transform:none;letter-spacing:0">edit bumpers →</a></h3>
      <div class="row" id="bu_list" style="max-height:240px;overflow:auto"><span class="sub">Loading…</span></div>
      <p class="sub">None ticked = use all of them. “Going into a break” only applies when commercial breaks are on.</p>
      <div class="form">${sourcePicker("bmp", "Video bumpers from Jellyfin (optional)", "Short clips (under 5 minutes) mixed in with the text bumpers at any spot.")}</div></div>`}
    <div class="card"><h2>Schedule</h2><div class="row" style="margin-bottom:10px">
      <span class="sub" id="poolinfo"></span><span class="spacer"></span>
      ${guide ? "" : `<button class="btn small" id="skip" title="Stop what's playing and move on. A show is skipped entirely; an ad or bumper just that one.">⏭ Skip what's on</button>
      <button class="btn small" id="rebuild" title="Re-read the library and reshuffle everything after what is on now">Rebuild schedule</button>
      <button class="btn small" id="rebuild_now" title="Re-read the library and start a fresh schedule right now, replacing what's on too">Rebuild including now</button>`}
      <button class="btn small" id="restart">Restart stream</button>
      <a class="btn small" href="/api/channels/${ch.id}/log" target="_blank">Log</a>
      <button class="btn small danger" id="delete">Delete channel</button></div>
      <div class="sched" id="sched"><p class="sub">${guide ? `The ${weather ? "weather" : "guide"} channel has no schedule of its own.` : "Loading…"}</p></div></div>
   </div>
   <div class="stack">
    <div class="card"><h2>On-screen graphics</h2>
      <div class="preview" id="pv"><div class="hint">Click “Preview” to render a frame with your logo and clock.</div></div>
      <div class="row" style="margin-top:10px"><button class="btn small" id="preview">Preview</button>${weather ? `<select id="pv_slide">${WX_SLIDES.map(([k, l]) => `<option value="${k}">${l.replace(/ \(.*/, "")}</option>`).join("")}</select>` : ""}<span class="sub">Save first to preview changes.</span></div>
      ${guide ? `
      <h3>Corner logo</h3>
      <p class="sub" style="margin-top:0">What sits in the top-left corner of the ${weather ? "weather" : "guide"} screen.</p>
      <div class="form">
        <label class="f">Show<select id="hl_mode">${HL_MODES.map(([v, l]) => `<option value="${v}" ${(hl.mode || "station") === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="f">Size: <span id="hl_size_val">${hl.size || 100}%</span><input type="range" id="hl_size" min="50" max="160" step="10" value="${hl.size || 100}"></label>
        <div class="row wide" id="hl_custom">${hl.file ? `<img src="/api/channels/${ch.id}/header_logo?v=${Date.now()}" class="hlthumb" alt="">` : ""}
          <input type="file" id="hlfile" accept="image/*" style="display:none">
          <button class="btn small" id="hl_upload">${hl.file ? "Replace image…" : "Upload image…"}</button>
          ${hl.file ? '<button class="btn small" id="hl_rm">Remove</button>' : '<span class="sub">PNG with a transparent background looks best.</span>'}</div>
        <label class="check wide" id="hl_recolor_l"><input type="checkbox" id="hl_recolor" ${hl.recolor ? "checked" : ""}> Recolour it to match the theme <span class="sub">(for one-colour logos on a transparent background)</span></label>
      </div>
      <h3>Channel logo</h3>
      <p class="sub" style="margin-top:0">Shown next to this channel in the guide listings, the TV page and app, and Jellyfin's Live TV.</p>
      <div class="row"><img src="${ch.logo_url}" style="height:48px;background:#0005;border-radius:6px;padding:4px" id="logoimg">
        <input type="file" id="logofile" accept="image/*" style="display:none">
        <button class="btn small" id="upload">Upload image…</button>
        ${logo.file ? '<button class="btn small" id="rmlogo">Remove</button>' : '<span class="sub">Using a generated badge</span>'}</div>` : `
      <h3>Channel logo (“bug”)</h3>
      <div class="row"><img src="${ch.logo_url}" style="height:48px;background:#0005;border-radius:6px;padding:4px" id="logoimg">
        <input type="file" id="logofile" accept="image/*" style="display:none">
        <button class="btn small" id="upload">Upload image…</button>
        ${logo.file ? '<button class="btn small" id="rmlogo">Remove</button>' : '<span class="sub">No logo shown on video</span>'}</div>
      <div class="row" style="margin-top:12px;align-items:flex-start">
        <div><div class="sub">Corner</div>${cornerPicker("logo", logo.position || "top-right")}</div>
        <div class="stack" style="gap:8px;flex:1">
          <label class="f">Size <input type="range" id="logo_size" min="4" max="30" value="${logo.size_percent || 12}"></label>
          <label class="f">Opacity <input type="range" id="logo_opacity" min="10" max="100" value="${Math.round((logo.opacity ?? 0.85) * 100)}"></label></div></div>
      <h3>Clock</h3>
      <label class="check"><input type="checkbox" id="clock_on" ${clock.enabled ? "checked" : ""}> Show the time on screen</label>
      <div class="row" style="margin-top:10px;align-items:flex-start">
        <div><div class="sub">Corner</div>${cornerPicker("clock", clock.position || "top-left")}</div>
        <div class="stack" style="gap:8px;flex:1">
          <label class="f">Format<select id="clock_fmt">${Object.entries(TH.clock_formats).map(([k, v]) => `<option value="${k}" ${(clock.format || "12h") === k ? "selected" : ""}>${{"12h": "12-hour", "12h_plain": "12-hour, no AM/PM", "12h_sec": "12-hour with seconds", "24h": "24-hour", "24h_sec": "24-hour with seconds"}[k]} (${v})</option>`).join("")}</select></label>
          <label class="f">Size <input type="range" id="clock_size" min="2" max="9" step="0.5" value="${clock.size_percent || 4.5}"></label></div></div>
      <div class="sub" style="margin-top:10px">Quick styles</div>
      <div class="presets">${Object.entries(CLOCK_PRESETS).map(([k, p]) => `<button class="btn small" data-preset="${k}">${p.label}</button>`).join("")}</div>
      <div class="form" style="margin-top:12px">
        <label class="f">Font<select id="clock_font">${fontOptions(clock.font, chTheme().fonts.clock, { clock: true })}</select></label>
        <label class="f">Colour<input type="color" id="clock_color" value="${esc(clock.color || "#ffffff")}"></label>
        <div class="fontsample wide" id="clock_sample" style="background:#000 linear-gradient(135deg,#2a3a5a,#556b2f);justify-content:center;font-size:34px"><span></span></div>
        <label class="f">Clock opacity: <span id="clock_op_val">${clock.opacity ?? 100}%</span>
          <input type="range" id="clock_op" min="10" max="100" step="5" value="${clock.opacity ?? 100}"></label>
        <label class="f">Bar behind the time: <span id="clock_bg_val">${clock.bg_opacity ?? 35}%</span>
          <input type="range" id="clock_bg" min="0" max="100" step="5" value="${clock.bg_opacity ?? 35}"></label>
        <label class="f">Outline<select id="clock_outline">${[["none", "None"], ["thin", "Thin"], ["thick", "Thick (Japanese TV style)"]].map(([v, l]) => `<option value="${v}" ${(clock.outline || "none") === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="check"><input type="checkbox" id="clock_shadow" ${clock.shadow !== false ? "checked" : ""}> Drop shadow</label></div>
      <p class="sub">The clock uses the Broadcast server's time zone. The 7-segment faces only have digits: pair them with 24-hour or “no AM/PM”.</p>
      <h3>“Up next” banner</h3>
      <label class="check"><input type="checkbox" id="un_on" ${un.enabled ? "checked" : ""}> Show the next show's title near the end of each program</label>
      <div class="form" style="margin-top:10px">
        <label class="f">Seconds before the end<input type="number" id="un_before" min="10" value="${un.seconds_before_end || 90}"></label>
        <label class="f">Show for (seconds)<input type="number" id="un_dur" min="3" value="${un.duration || 12}"></label></div>`}
    </div>
   </div>
  </div>`;

  let dirty = false;
  function markDirty() {
    if (dirty) return;
    dirty = true;
    $("#save").textContent = "Save changes";
    $("#save").classList.add("dirty");
    $("#unsaved").style.display = "";
  }
  const pickerBits = /-(q|list|type)$/;
  ["input", "change"].forEach((ev) => $(".editor").addEventListener(ev, (e) => {
    if (e.target.matches("input, select, textarea") && !pickerBits.test(e.target.id || "") && !e.target.closest("[data-nodirty]") &&
      !["logofile", "hlfile", "pv_slide"].includes(e.target.id)) markDirty();
  }));
  $$(".corners button").forEach((x) => x.addEventListener("click", markDirty));
  leaveGuard = (silent) => !dirty || (!silent && confirm("This channel has unsaved changes. Leave without saving?"));
  if (!guide) {
    wireSourcePicker("src", sources, markDirty); wireSourcePicker("exc", exclude, markDirty); wireSourcePicker("fil", fillers, markDirty);
    wireSourcePicker("brk", brSources, markDirty); wireSourcePicker("bmp", buSources, markDirty);
    api("GET", "bumpers").then((list) => {
      const ids = new Set(bu.ids || []);
      $("#bu_list").innerHTML = list.length ? list.map((b) => `<label class="check"><input type="checkbox" data-bump="${b.id}" ${ids.has(b.id) ? "checked" : ""}>
        ${esc(b.name)} <span class="badge">${esc(KIND_LABEL[b.kind] || b.kind)}</span></label>`).join("") : '<span class="sub">No text bumpers yet.</span>';
    });
  }
  $$(".corners").forEach((box) => $$("button", box).forEach((b) => (b.onclick = () => {
    $$("button", box).forEach((x) => x.classList.remove("on")); b.classList.add("on");
  })));
  const corner = (id) => ($(`[data-corner=${id}] button.on`) || {}).dataset?.pos;

  const collect = () => {
    const d = { name: $("#name").value.trim() || "Channel", number: parseFloat($("#number").value) || ch.number,
      group: $("#group").value.trim(), type: $("#type").value, enabled: $("#enabled").checked, kids: $("#kids").checked };
    if ($("#screen_off")) d.screen_off_minutes = +$("#screen_off").value || 0;
    if (guide) {
      d.music_path = $("#music_path").value.trim();
      if ($("#guide_scroll_speed")) d.guide_scroll_speed = +$("#guide_scroll_speed").value;
      if (weather) d.weather = { ...WX, location: { mode: $("#wx_mode").value, zip: $("#wx_zip").value.trim(), country: ($("#wx_country").value.trim() || "US").toUpperCase(),
          query: $("#wx_query").value.trim(), lat: $("#wx_lat").value.trim() === "" ? null : +$("#wx_lat").value, lon: $("#wx_lon").value.trim() === "" ? null : +$("#wx_lon").value,
          name: $("#wx_name").value.trim() },
        units: $("#wx_units").value, slides: $$("[data-wxslide]").filter((x) => x.checked).map((x) => x.dataset.wxslide),
        slide_seconds: Math.max(5, +$("#wx_secs").value || 10), radar_frames: +$("#wx_frames").value, alerts: $("#wx_alerts").checked,
        radar_min_dbz: $("#wx_mindbz").value === "all" ? "all" : +$("#wx_mindbz").value,
        crawl: $("#wx_crawl").checked, crawl_speed: +$("#wx_speed").value };
      d.clock = { ...clock, format: $("#guide_clock_fmt").value };
      d.theme = $("#theme").value; d.guide_font = $("#guide_font").value; d.guide_display_font = $("#guide_display_font").value;
      d.header_logo = { ...hl, mode: $("#hl_mode").value, size: +$("#hl_size").value, recolor: $("#hl_recolor").checked };
      return d;
    }
    Object.assign(d, { sources, exclude, filler_sources: fillers,
      item_types: $$("[data-itype]").filter((x) => x.checked).map((x) => x.dataset.itype),
      include_specials: $("#include_specials").checked, min_minutes: +$("#min_minutes").value || 0,
      max_minutes: +$("#max_minutes").value || 0, order: $("#order").value, no_repeat_show: $("#no_repeat_show").checked,
      balance: poolBalance(), slots: slots.map((s) => ({ ...s })),
      padding_minutes: +$("#padding_minutes").value,
      audio_language: $("#audio_language").value, normalize_audio: $("#normalize_audio").checked,
      subtitles: { mode: $("#sub_mode").value, language: $("#sub_lang").value, size: $("#sub_size").value, font: $("#sub_font").value,
        style: $("#sub_style").value, programs_only: $("#sub_prog").checked },
      music_path: $("#music_path").value.trim(),
      logo: { ...logo, position: corner("logo"), size_percent: +$("#logo_size").value, opacity: +$("#logo_opacity").value / 100 },
      theme: $("#theme").value,
      clock: { enabled: $("#clock_on").checked, position: corner("clock"), format: $("#clock_fmt").value, size_percent: +$("#clock_size").value,
        bg_opacity: +$("#clock_bg").value, font: $("#clock_font").value, color: $("#clock_color").value, opacity: +$("#clock_op").value,
        outline: $("#clock_outline").value, shadow: $("#clock_shadow").checked },
      up_next: { enabled: $("#un_on").checked, seconds_before_end: +$("#un_before").value || 90, duration: +$("#un_dur").value || 12 },
      breaks: { enabled: $("#br_on").checked, sources: brSources, interval_minutes: +$("#br_interval").value || 8,
        length_seconds: +$("#br_len").value || 120, min_tail_minutes: +$("#br_tail").value, max_per_program: +$("#br_max").value || 0,
        episodes: $("#br_eps").checked, movies: $("#br_movies").checked, use_chapters: $("#br_ch").checked, show_graphics: $("#br_gfx").checked,
        split: $("#br_split").checked, split_over_seconds: Math.max(20, +$("#br_split_over").value || 90) },
      bumpers: { enabled: $("#bu_on").checked, ids: $$("[data-bump]").filter((x) => x.checked).map((x) => x.dataset.bump), sources: buSources,
        every_breaks: +$("#bu_every").value || 1, into_break: $("#bu_into").checked, out_of_break: $("#bu_out").checked, between_programs: $("#bu_between").checked,
        show_graphics: $("#bu_gfx").checked } });
    if (!d.item_types.length) d.item_types = ["Movie", "Episode"];
    return d;
  };
  const save = async (quiet) => {
    const d = collect();
    const typeChanged = d.type !== ch.type;
    await api("PUT", "channels/" + ch.id, d);
    dirty = false;
    $("#save").textContent = "Save"; $("#save").classList.remove("dirty"); $("#unsaved").style.display = "none";
    $("h1").textContent = `${d.number} · ${d.name}`;
    if (!quiet) toast(d.sources && d.sources.length ? "Saved — building the schedule now" : "Saved");
    if (typeChanged) route();
loadStatus();
    return d;
  };
  $("#save").onclick = async () => { try { await save(); loadSchedule(); setTimeout(() => { loadPool && loadPool(); loadSlots && loadSlots(); }, 1500); } catch (e) { toast(e.message, true); } };
  $("#castbtn").onclick = () => castDialog(ch.id, `${ch.number} ${ch.name}`);
  if ($("#sub_check")) $("#sub_check").onclick = async () => {
    $("#sub_result").textContent = "Checking…";
    try {
      const r = await api("GET", `channels/${ch.id}/subtitles`);
      const tracks = (r.tracks || []).map((t) => `${esc(t.title || t.lang || "?")} <span class="badge">${esc(t.lang || "no language")}</span> <span class="badge">${esc(t.codec)}${t.text ? "" : " · picture"}${t.forced ? " · forced" : ""}${t.external ? " · separate file" : ""}</span>`);
      $("#sub_result").innerHTML = `<b>${r.ok ? "✅" : "⚠️"} ${esc(r.title || "")}</b>: ${esc(r.reason)}` +
        (r.audio ? `<br>Audio language: ${esc(r.audio)}` : "") +
        (tracks.length ? `<br>Subtitle tracks Jellyfin reports:<br>• ${tracks.join("<br>• ")}` : "") +
        (r.libass === false ? "<br>⚠️ This ffmpeg can't draw text subtitles (no libass). Point Settings → ffmpeg path at Jellyfin's ffmpeg." : "");
    } catch (e) { $("#sub_result").textContent = e.message; }
  };
  const drawClock = () => {
    if (!$("#clock_sample")) return;
    const span = $("#clock_sample span"), bg = +$("#clock_bg").value / 100, op = +$("#clock_op").value / 100;
    const ol = $("#clock_outline").value, c = $("#clock_color").value;
    sampleFont(span, resolveFont($("#clock_font").value, chTheme().fonts.clock), clockSample($("#clock_fmt").value));
    const w = ol === "thick" ? 4 : ol === "thin" ? 2 : 0;
    span.style.cssText += `;color:${c};opacity:${op};padding:2px 10px;background:rgba(0,0,0,${bg / Math.max(op, .01)});` +
      `text-shadow:${[w ? `-${w}px -${w}px 0 #000, ${w}px -${w}px 0 #000, -${w}px ${w}px 0 #000, ${w}px ${w}px 0 #000, 0 ${w}px 0 #000, 0 -${w}px 0 #000, ${w}px 0 0 #000, -${w}px 0 0 #000` : "",
        $("#clock_shadow").checked ? "3px 3px 2px rgba(0,0,0,.6)" : ""].filter(Boolean).join(",") || "none"}`;
    const v = +$("#clock_bg").value;
    $("#clock_bg_val").textContent = v === 0 ? "0% (just the time)" : v === 100 ? "100% (solid black)" : v + "%";
    $("#clock_op_val").textContent = $("#clock_op").value + "%";
  };
  const refreshThemeFonts = () => {   // the "Theme default (…)" options follow the theme picker
    const T = chTheme();
    [["#clock_font", T.fonts.clock, { clock: true }], ["#guide_font", T.fonts.guide], ["#guide_display_font", T.fonts.guide_display]].forEach(([sel, f, o]) => {
      const el = $(sel); if (el) { const v = el.value; el.innerHTML = fontOptions(v, f, o); }
    });
    drawClock(); drawGuideSample();
  };
  const drawGuideSample = () => {
    if (!$("#guide_sample")) return;
    const T = chTheme();
    sampleFont($("#guide_sample"), resolveFont($("#guide_font").value, T.fonts.guide));
  };
  $("#theme").onchange = refreshThemeFonts;
  $$("#clock_font, #clock_color, #clock_op, #clock_bg, #clock_outline, #clock_shadow, #clock_fmt").forEach((x) => x.addEventListener("input", drawClock));
  $$("#guide_font").forEach((x) => x.addEventListener("input", drawGuideSample));
  $$("[data-preset]").forEach((b) => (b.onclick = () => {
    const p = CLOCK_PRESETS[b.dataset.preset];
    $("#clock_font").value = p.font; $("#clock_color").value = p.color; $("#clock_op").value = p.opacity; $("#clock_bg").value = p.bg_opacity;
    $("#clock_outline").value = p.outline; $("#clock_shadow").checked = p.shadow; $("#clock_fmt").value = p.format;
    if (p.size_percent) $("#clock_size").value = p.size_percent;
    if (!$("#clock_on").checked) $("#clock_on").checked = true;
    drawClock(); markDirty();
  }));
  refreshThemeFonts();
  $("#preview").onclick = async () => {
    $("#pv").innerHTML = '<div class="hint">Rendering…</div>';
    const img = new Image();
    img.onload = () => { $("#pv").innerHTML = ""; $("#pv").appendChild(img); };
    img.onerror = async () => {
      let msg = "Preview failed"; try { msg = (await (await fetch(img.src)).json()).error; } catch { }
      $("#pv").innerHTML = `<div class="hint">${esc(msg)}</div>`;
    };
    img.src = `/api/channels/${ch.id}/preview.jpg?t=${Date.now()}` + ($("#pv_slide") ? "&slide=" + $("#pv_slide").value : "");
  };
  if (weather) {
    const modeVis = () => $$(".wxm").forEach((el) => (el.style.display = el.dataset.m === $("#wx_mode").value ? "" : "none"));
    $("#wx_mode").addEventListener("change", modeVis); modeVis();
    $("#wx_check").onclick = async () => {
      $("#wx_result").textContent = "Looking it up…";
      try {
        const r = await api("GET", `channels/${ch.id}/weather`);
        if (!r.location) throw new Error(r.error || "Couldn't find the location");
        const L = r.location;
        $("#wx_result").innerHTML = `📍 <b>${esc(L.name)}${L.region ? ", " + esc(L.region) : ""}</b> ${esc(L.country || "")} (${L.lat.toFixed(2)}, ${L.lon.toFixed(2)}, from ${esc(L.source)})` +
          (r.now ? ` · now <b>${esc(r.now)}</b>` : "") + (r.alerts ? ` · ⚠ ${r.alerts} alert(s)` : "") +
          (r.forecast_age_min !== undefined ? ` · forecast ${r.forecast_age_min < 2 ? "just updated" : r.forecast_age_min + " min old"}` : "") +
          (r.radar_age_min !== undefined ? ` · newest radar ${r.radar_age_min} min old` : "") +
          (Object.keys(r.errors || {}).length ? `<br>⚠ ${esc(Object.entries(r.errors).map(([k, v]) => k + ": " + v).join(" · "))}` : "");
      } catch (e) { $("#wx_result").textContent = "❌ " + e.message; }
    };
  }
  $("#restart").onclick = async () => { await api("POST", `channels/${ch.id}/restart`); toast("Stream restarting (viewers stay connected)"); };
  $("#delete").onclick = async () => {
    if (!confirm(`Delete channel ${ch.number} “${ch.name}”?`)) return;
    await api("DELETE", "channels/" + ch.id); location.hash = "#/channels";
  };
  const wireLogo = () => {
    $("#upload").onclick = () => $("#logofile").click();
    $("#logofile").onchange = async (ev) => {
      const f = ev.target.files[0]; if (!f) return;
      try { await save(true); await api("POST", `channels/${ch.id}/logo`, undefined, f); toast("Logo uploaded"); route(); }
      catch (e) { toast(e.message, true); }
    };
    if ($("#rmlogo")) $("#rmlogo").onclick = async () => { await api("DELETE", `channels/${ch.id}/logo`); route(); };
  };
  wireLogo();
  if (guide) {
    const hlShow = () => {
      const m = $("#hl_mode").value;
      $("#hl_custom").style.display = m === "custom" ? "" : "none";
      $("#hl_recolor_l").style.display = m === "channel" || m === "custom" ? "" : "none";
      $("#hl_size").closest("label").style.display = m === "none" ? "none" : "";
    };
    $("#hl_mode").addEventListener("change", hlShow); hlShow();
    $("#hl_size").addEventListener("input", () => ($("#hl_size_val").textContent = $("#hl_size").value + "%"));
    $("#hl_upload").onclick = () => $("#hlfile").click();
    $("#hlfile").onchange = async (ev) => {
      const f = ev.target.files[0]; if (!f) return;
      try { await save(true); await api("POST", `channels/${ch.id}/header_logo`, undefined, f); toast("Corner logo uploaded"); route(); }
      catch (e) { toast(e.message, true); }
    };
    if ($("#hl_rm")) $("#hl_rm").onclick = async () => { await save(true); await api("DELETE", `channels/${ch.id}/header_logo`); route(); };
  }
  if (!guide) {
    $("#skip").onclick = async () => {
      $("#skip").disabled = true;
      try { const r = await api("POST", `channels/${ch.id}/skip`); toast(r.skipped ? `Skipped “${r.skipped}”` : "Nothing on to skip"); loadSchedule(); }
      catch (e) { toast(e.message, true); } finally { setTimeout(() => ($("#skip").disabled = false), 1500); }
    };
    $("#rebuild_now").onclick = async () => {
      if (!confirm("Start a brand-new schedule right now? What's on will be replaced.")) return;
      $("#rebuild_now").disabled = true;
      try { await save(true); await api("POST", `channels/${ch.id}/rebuild_now`); toast("New schedule: starting now"); loadSchedule(); }
      catch (e) { toast(e.message, true); } finally { $("#rebuild_now").disabled = false; }
    };
    $("#rebuild").onclick = async () => {
      $("#rebuild").disabled = true;
      try { await save(true); await api("POST", `channels/${ch.id}/rebuild`); toast("Schedule rebuilt"); loadSchedule(); }
      catch (e) { toast(e.message, true); } finally { $("#rebuild").disabled = false; }
    };
  }
  // ---- commercial compilations: status of the ad finder, and a contact sheet of what it found
  const openComp = new Set();
  async function loadComp() {
    const box = $("#br_comp");
    if (!box || !document.body.contains(box)) return;
    let d;
    try { d = await api("GET", `channels/${ch.id}/commercials`); } catch { return; }
    if (!document.body.contains(box)) return;
    if (!d.files.length) { box.innerHTML = br.enabled && brSources.length ? `<p class="sub">${d.spots} commercials in rotation.</p>` : ""; return; }
    const done = d.files.filter((f) => f.state === "done");
    const busy = d.files.filter((f) => f.state === "scanning" || f.state === "queued");
    const head = `<div class="row"><b>${d.files.length} compilation${d.files.length > 1 ? "s" : ""}</b>
      <span class="sub">${done.reduce((n, f) => n + (f.mode === "whole" ? 1 : f.spots.length), 0)} ads found · ${d.spots} commercials in rotation${busy.length ? ` · scanning ${busy.length} more` : ""}${d.refreshing ? " · adding new ones…" : ""}</span></div>`;
    const row = (f) => {
      let st;
      if (f.state === "scanning") st = `<span class="badge">scanning ${f.progress || 0}%</span>`;
      else if (f.state === "queued" || f.state === "new") st = '<span class="badge">waiting to scan</span>';
      else if (f.state === "failed") st = `<span class="badge err" title="${esc(f.error)}">couldn't scan</span>`;
      else if (f.mode === "whole") st = `<span class="badge">played whole${f.duration > 600 ? " (too long: skipped)" : ""}</span>`;
      else st = `<span class="badge ok">${f.spots.length} ad${f.spots.length > 1 ? "s" : ""}</span>${f.method === "chapters" ? ' <span class="sub">from chapters</span>' : ""}`;
      const sheet = openComp.has(f.id) && f.state === "done" && f.mode !== "whole" ? `<div class="spotsheet">${f.spots.map(([a, b], n) => {
        const len = b - a, odd = !Object.keys({ 10: 1, 15: 1, 20: 1, 30: 1, 45: 1, 60: 1, 90: 1, 120: 1 }).some((s) => Math.abs(len - s) <= 1.5);
        return `<figure class="${odd ? "odd" : ""}"><img loading="lazy" src="/api/commercials/${f.id}/thumb.jpg?t=${(a + Math.min(1.5, len / 3)).toFixed(2)}" alt="">
          <figcaption>#${n + 1} · ${fmtLen(len)}<span class="sub"> at ${fmtLen(a)}</span></figcaption></figure>`;
      }).join("")}</div><p class="sub">One picture from the start of each ad. Odd lengths are outlined: usually two ads glued together or an ad cut in two. If a file came out badly, “Don't split” plays it as one piece (only if it's 10 minutes or less).</p>` : "";
      return `<div class="comprow"><div class="row"><span class="t">${esc(f.title)}</span><span class="sub">${fmtLen(f.duration)}</span>${st}<span class="spacer"></span>
        ${f.state === "done" && f.mode !== "whole" ? `<button class="btn small" data-cview="${f.id}">${openComp.has(f.id) ? "Hide" : "Review"}</button>` : ""}
        ${f.state === "done" || f.state === "failed" ? `<button class="btn small" data-crescan="${f.id}">Rescan</button>` : ""}
        <button class="btn small" data-cmode="${f.id}" data-to="${f.mode === "whole" ? "auto" : "whole"}">${f.mode === "whole" ? "Split it" : "Don't split"}</button></div>${sheet}</div>`;
    };
    box.innerHTML = head + d.files.map(row).join("");
    $$("[data-cview]", box).forEach((b) => (b.onclick = () => { openComp.has(b.dataset.cview) ? openComp.delete(b.dataset.cview) : openComp.add(b.dataset.cview); loadComp(); }));
    $$("[data-crescan]", box).forEach((b) => (b.onclick = async () => { await api("POST", `commercials/${b.dataset.crescan}/rescan`); loadComp(); }));
    $$("[data-cmode]", box).forEach((b) => (b.onclick = async () => { await api("POST", `commercials/${b.dataset.cmode}/mode`, { mode: b.dataset.to }); loadComp(); }));
    if (busy.length || d.refreshing) setTimeout(loadComp, 3000);
  }
  if (!guide) loadComp();
  // ---- time slots
  const DAYN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const SLOT_ORDER = { sequential: "In order: the next episode each time", shuffle: "Shuffle: everything once before repeats", random: "Random" };
  const SLOT_LEAD = { fit: "Start on time: whatever's before it ends early (a shorter show or filler fills the gap)",
    cut: "Start on time: cut off whatever is playing", late: "Wait for the show that's on to finish (the slot starts late)" };
  const SLOT_OVER = { fit: "End on time: don't start anything that would run past the end", finish: "Let the last one finish, even past the end time",
    cut: "Cut off at the end time" };
  let SLOTINFO = {}, editing = -1, editCopy = null;
  const hm2min = (s) => { const [h, m] = (s || "0:0").split(":").map(Number); return h * 60 + m; };
  const fmtHM = (s) => { const [h, m] = (s || "0:0").split(":").map(Number); return new Date(2000, 0, 1, h % 24, m).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); };
  const daysText = (d) => { const k = [...d].sort().join("");
    return k === "0123456" ? "Every day" : k === "01234" ? "Mon–Fri" : k === "56" ? "Weekends" : k === "" ? "No days picked" : [...d].sort().map((x) => DAYN[x]).join(", "); };
  const slotName = (s) => s.name || (SLOTINFO[s.id] && SLOTINFO[s.id].label) || s.sources.map((x) => x.name).join(", ") || "New time slot";
  const slotWhen = (s) => (s.repeat === "once" ? (s.date ? new Date(s.date + "T12:00").toLocaleDateString([], { weekday: "short", month: "short", day: "numeric", year: "numeric" }) : "No date picked") : daysText(s.days)) +
    " · " + (s.play === "one" ? `at ${fmtHM(s.start)}, one ${s.order === "sequential" ? "episode" : "program"}` : `${fmtHM(s.start)} – ${fmtHM(s.end)}`);
  function slotRanges(s) {    // [[weekday, startMin, endMin]] in "minutes of the week", for overlap warnings
    if (!s.enabled || s.repeat === "once") return [];
    const a = hm2min(s.start), b = s.play === "one" ? a + 30 : (hm2min(s.end) <= a ? hm2min(s.end) + 1440 : hm2min(s.end));
    return s.days.map((d) => [d * 1440 + a, d * 1440 + b]);
  }
  function slotWarnings(i) {
    const s = slots[i], w = [];
    if (!s.sources.length) w.push("Pick what plays in this slot.");
    if (s.repeat === "weekly" && !s.days.length) w.push("Pick at least one day.");
    if (s.repeat === "once" && !s.date) w.push("Pick a date.");
    if (s.play === "fill" && s.start === s.end) w.push("Start and end are the same time.");
    const mine = slotRanges(s);
    slots.forEach((o, j) => {
      if (j === i) return;
      const hit = slotRanges(o).some(([a, b]) => mine.some(([c, d]) => [[0], [7 * 1440], [-7 * 1440]].some(([sh]) => c + sh < b && a < d + sh)));
      if (hit) w.push(`Overlaps “${slotName(o)}”. When they overlap, the one that starts first plays and the other is skipped that day${o.play === "one" || s.play === "one" ? "" : ""}.`);
    });
    const inf = SLOTINFO[s.id];
    if (inf && s.sources.length && !inf.items && !dirty) w.push("Nothing found in Jellyfin for this yet.");
    return w;
  }
  function drawSlots() {
    if (!$("#slotlist")) return;
    $("#slotlist").innerHTML = slots.length ? slots.map((s, i) => {
      const inf = SLOTINFO[s.id] || {}, warn = slotWarnings(i);
      const next = (inf.airings || [])[0];
      return `<div class="slotrow ${s.enabled ? "" : "off"} ${editing === i ? "editing" : ""}">
        <label class="check" title="On / off"><input type="checkbox" data-slon="${i}" ${s.enabled ? "checked" : ""}></label>
        <div class="slotmain"><b>${esc(slotName(s))}</b> <span class="sub">${esc(slotWhen(s))}</span>
          <div class="sub">${s.play === "fill" ? esc(SLOT_ORDER[s.order].split(":")[0]) : ""}${inf.items ? `${s.play === "fill" ? " · " : ""}${inf.items} item${inf.items > 1 ? "s" : ""} (${inf.hours} h)` : ""}${s.exclusive ? " · only in this slot" : ""}</div>
          ${next && s.enabled ? `<div class="sub">Next: <b>${fmtDay(next.start)} ${fmtTime(next.start)}</b> · ${next.programs.map((p) => esc(p.subtitle ? `${p.subtitle}${p.title && s.order !== "sequential" ? " " + p.title : ""}` : p.title)).join(", ")}</div>` : ""}
          ${inf.episodes && s.enabled ? `<div class="sub" data-nodirty>Next episode: <select data-slnext="${i}" class="small">${inf.episodes.map((e) =>
            `<option value="${esc(e.id)}" ${e.id === inf.next_id ? "selected" : ""}>${esc(e.label)}</option>`).join("")}</select></div>` : ""}
          ${warn.map((x) => `<div class="sub warn">⚠ ${esc(x)}</div>`).join("")}</div>
        <div class="row" style="gap:6px"><button class="btn small" data-sled="${i}">Edit</button><button class="btn small" data-sldel="${i}" title="Delete">✕</button></div></div>`;
    }).join("") : '<p class="sub">No time slots yet: this channel plays its regular programming around the clock.</p>';
    $$("[data-slon]").forEach((x) => (x.onchange = () => { slots[+x.dataset.slon].enabled = x.checked; markDirty(); drawSlots(); }));
    $$("[data-sled]").forEach((x) => (x.onclick = () => openSlot(+x.dataset.sled)));
    $$("[data-sldel]").forEach((x) => (x.onclick = () => {
      const i = +x.dataset.sldel;
      if (!confirm(`Delete the time slot “${slotName(slots[i])}”?`)) return;
      slots.splice(i, 1); if (editing === i) closeSlot(); else if (editing > i) editing--;
      markDirty(); drawSlots();
    }));
    $$("[data-slnext]").forEach((x) => (x.onchange = async () => {
      const s = slots[+x.dataset.slnext];
      if (dirty) { toast("Save your changes first, then pick the next episode", true); drawSlots(); return; }
      try {
        const r = await api("POST", `channels/${ch.id}/slots/${encodeURIComponent(s.id)}/next`, { id: x.value });
        SLOTINFO = Object.fromEntries(r.map((z) => [z.id, z])); drawSlots(); loadSchedule();
        toast("Next episode set: the schedule after what's on now was re-planned");
      } catch (e) { toast(e.message, true); }
    }));
  }
  function slotForm(s) {
    return `<div class="form">
      <label class="f wide">Name (optional, shown in this list)<input type="text" id="sl_name" value="${esc(s.name)}" placeholder="e.g. Prime time Simpsons"></label>
      ${sourcePicker("sl", "What plays", "A series, a collection, a playlist, a genre… anything you can add to a channel. It doesn't have to be in the channel's regular programming.")}
      <label class="f">Repeats<select id="sl_repeat"><option value="weekly">Every week</option><option value="once" ${s.repeat === "once" ? "selected" : ""}>Just once</option></select></label>
      <label class="f" id="sl_date_w">Date<input type="date" id="sl_date" value="${esc(s.date)}"></label>
      <div class="wide" id="sl_days_w"><h3>Days</h3><div class="row" style="gap:6px;flex-wrap:wrap">
        ${DAYN.map((d, i) => `<button type="button" class="btn small ${s.days.includes(i) ? "primary" : ""}" data-sday="${i}">${d}</button>`).join("")}
        <span class="sub" style="margin:0 4px">or</span>
        <button type="button" class="btn small" data-sdays="01234">Mon–Fri</button><button type="button" class="btn small" data-sdays="56">Weekends</button>
        <button type="button" class="btn small" data-sdays="0123456">Every day</button></div></div>
      <label class="f">Plays<select id="sl_play"><option value="fill">From the start time to the end time</option>
        <option value="one" ${s.play === "one" ? "selected" : ""}>One episode or movie at the start time</option></select></label>
      <label class="f">Starts at<input type="time" id="sl_start" value="${esc(s.start)}"></label>
      <label class="f" id="sl_end_w">Ends at<input type="time" id="sl_end" value="${esc(s.end === "24:00" ? "00:00" : s.end)}"><span class="sub">Earlier than the start = past midnight</span></label>
      <label class="f wide">Order<select id="sl_order">${Object.entries(SLOT_ORDER).map(([k, v]) => `<option value="${k}" ${s.order === k ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <label class="f wide">When it's time to start<select id="sl_lead">${Object.entries(SLOT_LEAD).map(([k, v]) => `<option value="${k}" ${s.lead_in === k ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <label class="f wide" id="sl_over_w">If the next one would run past the end<select id="sl_over">${Object.entries(SLOT_OVER).map(([k, v]) => `<option value="${k}" ${s.overrun === k ? "selected" : ""}>${v}</option>`).join("")}</select>
        <span class="sub">Leftover time before the end gets the channel's filler and an “Up Next” card.</span></label>
      <label class="check wide"><input type="checkbox" id="sl_breaks" ${s.breaks ? "checked" : ""}> Commercial breaks during the slot (the channel's own break settings)</label>
      <label class="check wide"><input type="checkbox" id="sl_excl" ${s.exclusive ? "checked" : ""}> Only show this in its time slot <span class="sub">(take it out of the channel's regular programming)</span></label>
      <details class="wide" id="sl_range_w" ${s.from_date || s.until_date ? "open" : ""}><summary class="sub">Only between certain dates (e.g. a holiday season)</summary>
        <div class="row" style="gap:12px;margin-top:8px"><label class="f">From<input type="date" id="sl_from" value="${esc(s.from_date)}"></label>
        <label class="f">Until<input type="date" id="sl_until" value="${esc(s.until_date)}"></label></div></details>
    </div>
    <div class="row" style="margin-top:12px"><button class="btn primary" id="sl_done">Done</button><button class="btn" id="sl_cancel">Cancel</button>
      <span class="sub">Then <b>Save</b> the channel to put it on the schedule.</span></div>`;
  }
  function openSlot(i) {
    editing = i; editCopy = JSON.parse(JSON.stringify(slots[i]));
    const s = slots[i], ed = $("#sloted");
    ed.innerHTML = slotForm(s); ed.style.display = "";
    wireSourcePicker("sl", s.sources, () => { markDirty(); drawSlots(); });
    const sync = () => {
      s.name = $("#sl_name").value.trim(); s.repeat = $("#sl_repeat").value; s.date = $("#sl_date").value; s.play = $("#sl_play").value;
      s.start = $("#sl_start").value || "20:00"; s.end = $("#sl_end").value || "21:00"; s.order = $("#sl_order").value; s.lead_in = $("#sl_lead").value;
      s.overrun = $("#sl_over").value; s.breaks = $("#sl_breaks").checked; s.exclusive = $("#sl_excl").checked;
      s.from_date = $("#sl_from").value; s.until_date = $("#sl_until").value;
      const once = s.repeat === "once", one = s.play === "one";
      $("#sl_date_w").style.display = once ? "" : "none"; $("#sl_days_w").style.display = once ? "none" : "";
      $("#sl_range_w").style.display = once ? "none" : ""; $("#sl_end_w").style.display = one ? "none" : ""; $("#sl_over_w").style.display = one ? "none" : "";
      drawSlots();
    };
    $$("input, select", ed).forEach((x) => { if (!/^sl-/.test(x.id)) x.addEventListener(x.type === "text" ? "input" : "change", sync); });
    const days = () => $$("[data-sday]").forEach((b) => b.classList.toggle("primary", s.days.includes(+b.dataset.sday)));
    $$("[data-sday]").forEach((b) => (b.onclick = () => { const d = +b.dataset.sday; s.days = s.days.includes(d) ? s.days.filter((x) => x !== d) : [...s.days, d].sort(); days(); markDirty(); drawSlots(); }));
    $$("[data-sdays]").forEach((b) => (b.onclick = () => { s.days = b.dataset.sdays.split("").map(Number); days(); markDirty(); drawSlots(); }));
    $("#sl_done").onclick = closeSlot;
    $("#sl_cancel").onclick = () => { if (editCopy) slots[editing] = editCopy; if (editCopy && editCopy._new) slots.splice(editing, 1); closeSlot(); };
    sync(); ed.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  function closeSlot() {
    if (editing >= 0 && slots[editing]) delete slots[editing]._new;
    editing = -1; editCopy = null; $("#sloted").style.display = "none"; $("#sloted").innerHTML = ""; drawSlots();
  }
  async function loadSlots() {
    if (guide || !$("#slotlist")) return;
    try { SLOTINFO = Object.fromEntries((await api("GET", `channels/${ch.id}/slots`)).map((z) => [z.id, z])); } catch { /* shown as plain list */ }
    drawSlots();
  }
  if (!guide) {
    $("#slot_add").onclick = () => {
      if (editing >= 0) closeSlot();
      slots.push({ id: "ts" + Date.now().toString(36), enabled: true, name: "", sources: [], repeat: "weekly", days: [0, 1, 2, 3, 4], date: "",
        from_date: "", until_date: "", start: "20:00", end: "21:00", play: "fill", order: "sequential", lead_in: "fit", overrun: "fit",
        breaks: true, exclusive: false, _new: true });
      markDirty(); openSlot(slots.length - 1);
      $("#sl_cancel").onclick = () => { slots.pop(); closeSlot(); };
    };
    drawSlots(); loadSlots();
  }

  // ---- pool breakdown & airtime balancing
  const PIE = ["#ffb000", "#4f8cff", "#ff5d73", "#34d399", "#a78bfa", "#f97316", "#22d3ee", "#e879f9", "#a3e635", "#fb7185", "#60a5fa", "#fbbf24"];
  let POOL = null, poolMode = "hours";
  const balW = { ...(((ch.balance || {}).weights) || {}) };
  function poolBalance() { const w = {}; for (const [k, v] of Object.entries(balW)) if (Math.abs(v - 1) > 1e-6) w[k] = v; return { strength: +($("#bal_strength")?.value || 0), weights: w }; }
  const balanced = () => { const b = poolBalance(); return b.strength > 0 || Object.keys(b.weights).length > 0; };
  function planShares(groups) {       // same maths as the server (scheduler.target_shares)
    const b = poolBalance(), a = b.strength / 100, total = groups.reduce((s, g) => s + g.seconds, 0) || 1;
    const raw = groups.map((g) => { const n = g.seconds / total; return (n > 0 ? n ** (1 - a) : 0) * (b.weights[g.key] ?? 1); });
    const sum = raw.reduce((s, v) => s + v, 0) || 1;
    return raw.map((v) => v / sum);
  }
  const fmtH = (s) => s >= 3600 ? (s / 3600).toFixed(s >= 36000 ? 0 : 1) + " h" : Math.round(s / 60) + " min";
  const wLabel = (m) => "×" + (+m.toFixed(2));
  function drawPool() {
    if (!POOL || !$("#pool_pie")) return;
    const G = POOL.groups;
    $$("[data-pm]").forEach((b) => b.classList.toggle("primary", b.dataset.pm === poolMode));
    $("#bal_val").textContent = +$("#bal_strength").value ? $("#bal_strength").value + "%" : "off";
    if (!G.length) { $("#pool_total").textContent = "Nothing in the pool yet: add some sources and save."; $("#pool_pie").innerHTML = ""; $("#pool_legend").innerHTML = ""; return; }
    const plan = planShares(G), totalS = G.reduce((s, g) => s + g.seconds, 0), totalN = G.reduce((s, g) => s + g.items, 0);
    const val = (g, i) => poolMode === "items" ? g.share_items : poolMode === "hours" ? g.share_time : poolMode === "plan" ? (balanced() ? plan[i] : g.share_time) : g.scheduled;
    $("#pool_total").textContent = poolMode === "items" ? `${totalN} items in ${G.length} show${G.length > 1 ? "s" : ""}` :
      poolMode === "hours" ? `${fmtH(totalS)} of programmes` : poolMode === "plan" ? (balanced() ? "the airtime each show will get" : "balancing is off: airtime follows the pool")
      : POOL.scheduled_hours ? `what's actually scheduled in the next ${POOL.scheduled_hours} h` : "nothing scheduled yet";
    // pie (slices under 2% are drawn together)
    let a0 = -Math.PI / 2, paths = "", other = 0;
    const arc = (v, color, title) => {
      if (v <= 0) return;
      if (v >= 0.9999) { paths += `<circle r="100" fill="${color}"><title>${esc(title)}</title></circle>`; return; }
      const a1 = a0 + v * 2 * Math.PI, large = v > 0.5 ? 1 : 0;
      paths += `<path d="M0 0 L${100 * Math.cos(a0)} ${100 * Math.sin(a0)} A100 100 0 ${large} 1 ${100 * Math.cos(a1)} ${100 * Math.sin(a1)} Z" fill="${color}"><title>${esc(title)} · ${(v * 100).toFixed(1)}%</title></path>`;
      a0 = a1;
    };
    G.forEach((g, i) => { const v = val(g, i); if (v < 0.02) other += v; else arc(v, PIE[i % PIE.length], g.title); });
    arc(other, "#6b7280", "Others");
    $("#pool_pie").innerHTML = paths + `<circle r="52" fill="var(--panel, #111)"/>`;
    $("#pool_legend").innerHTML = `<table class="pooltab"><tr><th></th><th>Show</th><th>Items</th><th>Hours</th><th>%</th><th title="More or less airtime for this show, on top of the balancing above">Weight</th></tr>${G.map((g, i) => {
      const m = balW[g.key] ?? 1, share = plan[i], back = balanced() && share > 0 ? g.seconds / share / 86400 : null;
      return `<tr><td><i class="dot" style="background:${val(g, i) < 0.02 ? "#6b7280" : PIE[i % PIE.length]}"></i></td><td class="t" title="${esc(g.title)}">${esc(g.title)}</td>
        <td>${g.items}</td><td>${fmtH(g.seconds)}</td><td><b>${(val(g, i) * 100).toFixed(val(g, i) < 0.1 ? 1 : 0)}%</b></td>
        <td class="w"><span class="wr"><input type="range" min="-2" max="2" step="0.25" value="${Math.log2(m)}" data-bw="${esc(g.key)}" aria-label="Weight for ${esc(g.title)}"><span>${wLabel(m)}</span></span>
        ${back !== null && back < 2 ? `<small class="warn" title="With this much airtime every episode has aired and the show starts over about this often">all of it every ${back < 1 ? Math.max(1, Math.round(back * 24)) + " h" : back.toFixed(1) + " days"}</small>` : ""}</td></tr>`;
    }).join("")}</table>${noRepeatCap(plan)}`;
    $$("[data-bw]").forEach((r) => (r.oninput = () => {
      balW[r.dataset.bw] = 2 ** +r.value;
      r.nextElementSibling.textContent = wLabel(balW[r.dataset.bw]);
      if (poolMode !== "plan") poolMode = "plan";
      drawPool(); markDirty();
    }));
    $("#bal_note").textContent = balanced() ? "Balancing is on." : "Balancing is off (the channel plays the pool as it is).";
  }
  function noRepeatCap(plan) {    // "never twice in a row" means one show can't fill more than every other slot
    if (!$("#no_repeat_show").checked || POOL.groups.length < 2 || !["plan", "sched"].includes(poolMode)) return "";
    const i = plan.findIndex((v) => v > 0.52);
    if (i < 0 || !(balanced() || poolMode === "sched")) return "";
    return `<p class="sub warn">${esc(POOL.groups[i].title)} is set for ${Math.round(plan[i] * 100)}%, but with “Never play the same show twice in a row” on it can only air every other slot (about half the time, depending on running times).</p>`;
  }
  async function loadPool() {
    if (guide || !$("#pool_pie")) return;
    try { POOL = await api("GET", `channels/${ch.id}/breakdown`); } catch (e) { $("#pool_total").textContent = e.message; return; }
    drawPool();
  }
  if (!guide) {
    $$("[data-pm]").forEach((b) => (b.onclick = () => { poolMode = b.dataset.pm; drawPool(); }));
    $("#bal_strength").addEventListener("input", () => { poolMode = "plan"; drawPool(); });
    $("#bal_reset").onclick = () => { $("#bal_strength").value = 0; for (const k of Object.keys(balW)) delete balW[k]; poolMode = "hours"; drawPool(); markDirty(); };
    loadPool();
  }
  async function loadSchedule() {
    if (guide) return;
    try {
      const [s, full] = await Promise.all([api("GET", `channels/${ch.id}/schedule?hours=24`), api("GET", "channels/" + ch.id)]);
      const now = Date.now() / 1000;
      if (full.pool) $("#poolinfo").textContent = `${full.pool.items} items (${full.pool.hours} hours) in rotation` +
        (full.pool.fillers ? `, ${full.pool.fillers} fillers` : "") + (full.pool.commercials ? `, ${full.pool.commercials} commercials` : "") +
        (full.pool.video_bumpers ? `, ${full.pool.video_bumpers} video bumpers` : "") + (full.pool.error ? ` — ${full.pool.error}` : "");
      let lastDay = "";
      $("#sched").innerHTML = s.length ? `<table>${s.map((e) => {
        const day = fmtDay(e.start); const hdr = day !== lastDay ? `<tr><td colspan="2" class="sub"><b>${day}</b></td></tr>` : ""; lastDay = day;
        return hdr + `<tr class="${e.start <= now && now < e.end ? "on" : ""}"><td class="t">${fmtTime(e.start)}</td>
          <td>${e.slot ? '<span title="Time slot">📅</span> ' : ""}<b>${esc(e.title)}</b> <span class="sub">${esc(e.subtitle || "")}</span></td></tr>`;
      }).join("")}</table>` : '<p class="sub">Nothing scheduled — add some sources and save.</p>';
      const on = $("#sched tr.on"); if (on) $("#sched").scrollTop = on.offsetTop - 40;
    } catch (e) { $("#sched").innerHTML = `<p class="sub">${esc(e.message)}</p>`; }
  }
  loadSchedule();
}

// --------------------------------------------------------------------------- bumpers
const KIND_LABEL = { into_break: "Into break", out_of_break: "Back from break", next: "Before next show", any: "Anywhere" };
const VARS = [["show", "the show that's on"], ["episode", "episode title"], ["next", "next show"], ["next_time", "when it starts"],
  ["channel", "channel name"], ["number", "channel number"], ["station", "station name"], ["time", "current time"], ["day", "weekday"]];
const WX_VARS = [["weather", "“41° and light rain”"], ["temp", "temperature now"], ["feels_like", "feels-like temperature"],
  ["conditions", "“light rain”"], ["high", "today's high"], ["low", "today's low"], ["rain_chance", "chance of rain today"],
  ["wind", "wind speed"], ["humidity", "humidity"], ["tomorrow", "tomorrow's conditions"], ["tomorrow_high", "tomorrow's high"],
  ["sunrise", "sunrise time"], ["sunset", "sunset time"], ["city", "the forecast's town"], ["weather_channel", "weather channel name"],
  ["weather_number", "weather channel number"]];
const WHEN_LABEL = { "": "Any time", late_night: "Late night (11 PM – 5 AM)", morning: "Mornings (5 – 11 AM)", daytime: "Daytime (11 AM – 5 PM)",
  evening: "Evenings (5 – 11 PM)", weekend: "Weekends", rain: "When it's raining", snow: "When it's snowing", storm: "During thunderstorms",
  clear: "When skies are clear", cloudy: "When it's cloudy", fog: "When it's foggy", hot: "When it's hot (85°F / 29°C or more)",
  cold: "When it's cold (40°F / 4°C or less)", freezing: "When it's freezing (32°F / 0°C or less)", windy: "When it's windy (20 mph or more)",
  nice: "When it's nice out (62–80°F, clear)" };
const WHEN_SHORT = { late_night: "late night", morning: "mornings", daytime: "daytime", evening: "evenings", weekend: "weekends",
  rain: "rain", snow: "snow", storm: "storms", clear: "clear", cloudy: "cloudy", fog: "fog", hot: "hot", cold: "cold", freezing: "freezing",
  windy: "windy", nice: "nice out" };
const TIME_WHEN = ["late_night", "morning", "daytime", "evening", "weekend"];
async function renderCardImg(bumper, card) {
  const r = await fetch("/api/bumpers/render", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ bumper, card }) });
  if (!r.ok) throw new Error(await r.text());
  return URL.createObjectURL(await r.blob());
}
let bumperFilter = "all";
async function showBumpers() {
  const [list, packs, settings] = await Promise.all([api("GET", "bumpers"), api("GET", "bumpers/packs").catch(() => ({})),
    api("GET", "settings").catch(() => ({}))]);
  const FILTERS = [["all", "All"], ["into_break", "Into break"], ["out_of_break", "Back from break"], ["next", "Before next show"], ["any", "Anywhere"],
    ["weather", "Weather"], ["time", "Time of day"]];
  bumperFilter = sessionStorage.getItem("jfb-bf") || "all";
  const matchF = (f, b) => f === "all" || b.kind === f || (f === "weather" && b.weather) || (f === "time" && TIME_WHEN.includes(b.when));
  const match = (b) => matchF(bumperFilter, b);
  const wxNote = packs.weather_bumpers ? (packs.weather_channel
    ? `<p class="sub">🌤 ${packs.weather_values && packs.weather_values.weather ? `Right now: ${esc(packs.weather_values.weather)}${packs.weather_values.city ? " in " + esc(packs.weather_values.city) : ""}.` : "Waiting for the forecast."}
       Weather bumpers quote your weather channel's forecast, and ones marked for rain, cold, etc. only air when that's actually happening.</p>`
    : `<p class="sub">🌤 ${packs.weather_bumpers} bumpers talk about the weather. They stay off the air until you add a weather channel (Channels → New → Weather channel).</p>`) : "";
  view.innerHTML = `<div class="row" style="margin-bottom:8px"><h1 style="margin:0">Bumpers</h1><span class="spacer"></span>
    ${packs.missing ? `<button class="btn" id="restore" title="Bring back built-in bumpers you deleted">Restore ${packs.missing} built-in bumper${packs.missing > 1 ? "s" : ""}</button>` : ""}
    <a class="btn primary" href="#/bumper/new">+ New bumper</a></div>
    <p class="sub" style="margin-bottom:8px">Short text cards between shows and around commercial breaks: simple words on a plain background, a beat of black between cards.
      Turn them on per channel under <b>Edit channel → Bumpers</b>. Text can include live details like <code>{show}</code>, <code>{next}</code>, <code>{time}</code> or <code>{weather}</code>.</p>
    ${wxNote}
    <div class="card" style="margin:12px 0"><div class="row" style="align-items:flex-end;gap:12px">
      <label class="f" style="flex:1">🎵 Default music for bumpers (a file or a folder on the Broadcast server; a folder plays a random track each time)
        <input type="text" id="bmusic" value="${esc(settings.bumper_music_path || "")}" placeholder="e.g. D:\Music\Bumper Beds"></label>
      <button class="btn" id="bmusic_save">Save</button></div>
      <div class="sub" id="bmusic_info" style="margin-top:6px">Used by every text bumper that doesn't pick its own music. With nothing set, bumpers use the channel's music, or play silent.</div>
      <div class="row" style="align-items:flex-end;gap:16px;margin-top:12px;flex-wrap:wrap">
        <label class="check" style="flex:1;min-width:260px"><input type="checkbox" id="mlevel_match" ${settings.music_match_loudness !== false ? "checked" : ""}>
          Match music to the shows' volume <span class="sub">(recommended: music is mastered much louder than TV, so each track is measured once and turned down to match)</span></label>
        <label class="f" style="min-width:260px">🔊 Music volume: <b id="mlevel_val"></b>
          <input type="range" id="mlevel" min="-30" max="10" step="1" value="${+settings.music_volume_db || 0}">
          <span class="row sub" style="justify-content:space-between"><span>quieter</span><span>louder</span></span></label></div>
      <div class="sub" style="margin-top:4px">Applies to all background music: bumpers, “Up Next” cards, the guide and the weather channel. Changes apply from the next bumper or card.</div></div>
    <div class="presets" style="margin:12px 0 16px">${FILTERS.map(([k, l]) => `<button class="btn small ${bumperFilter === k ? "primary" : ""}" data-bf="${k}">${l} <span class="sub">${list.filter((b) => matchF(k, b)).length}</span></button>`).join("")}</div>
    <div class="bgrid"></div>`;
  $$("[data-bf]").forEach((x) => {
    x.onclick = () => { bumperFilter = x.dataset.bf; sessionStorage.setItem("jfb-bf", bumperFilter); showBumpers(); }; });
  const musicInfo = async () => {
    const path = $("#bmusic").value.trim();
    if (!path) { $("#bmusic_info").textContent = "Used by every text bumper that doesn't pick its own music. With nothing set, bumpers use the channel's music, or play silent."; return; }
    try {
      const r = await api("GET", "bumpers/music_check?path=" + encodeURIComponent(path));
      $("#bmusic_info").textContent = r.kind === "folder" ? (r.files ? `✓ Folder with ${r.files >= 5000 ? "5000+" : r.files} audio file${r.files === 1 ? "" : "s"}: a random one plays under each bumper.` : "⚠ That folder has no audio files (mp3, m4a, aac, flac, ogg, opus, wav).")
        : r.kind === "file" ? (r.ok ? `✓ ${r.name} plays under every bumper.` : "⚠ That file isn't an audio type the bumpers can use.")
        : "⚠ Not found on the Broadcast server. Use a path as that computer sees it.";
      if (r.measurable && $("#mlevel_match").checked && r.measured < r.measurable) {
        $("#bmusic_info").textContent += ` Measuring volume: ${r.measured} of ${r.measurable} done (in the background; unmeasured tracks are turned down by a typical amount meanwhile).`;
        clearTimeout(musicInfo.t); musicInfo.t = setTimeout(() => { if ($("#bmusic_info")) musicInfo(); }, 5000);
      }
    } catch (e) { $("#bmusic_info").textContent = e.message; }
  };
  musicInfo();
  const mlevelText = () => {
    const v = +$("#mlevel").value;
    $("#mlevel_val").textContent = v === 0 ? ($("#mlevel_match").checked ? "matched" : "as recorded") : (v > 0 ? "+" : "") + v + " dB";
  };
  mlevelText();
  const musicDirty = () => $("#bmusic_save").classList.add("primary");
  $("#mlevel").oninput = () => { mlevelText(); musicDirty(); };
  $("#mlevel_match").onchange = () => { mlevelText(); musicDirty(); };
  $("#bmusic").addEventListener("input", musicDirty);
  $("#bmusic_save").onclick = async () => {
    try {
      await api("POST", "settings", { bumper_music_path: $("#bmusic").value.trim().replace(/^"|"$/g, ""),
        music_match_loudness: $("#mlevel_match").checked, music_volume_db: +$("#mlevel").value });
      toast("Music settings saved"); $("#bmusic_save").classList.remove("primary"); musicInfo();
    }
    catch (e) { toast(e.message, true); }
  };
  $("#bmusic").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#bmusic_save").click(); });
  if ($("#restore")) $("#restore").onclick = async () => { const r = await api("POST", "bumpers/restore"); toast(`Restored ${r.restored} bumpers`); showBumpers(); };
  const shown = list.filter(match);
  $(".bgrid").innerHTML = `${shown.map((b) => `<div class="card stack" style="gap:10px">
      <img class="bthumb" data-thumb="${b.id}" alt="">
      <b>${esc(b.name)}</b><div class="row" style="gap:6px">${b.when ? `<span class="badge" title="${esc(WHEN_LABEL[b.when] || "")}">${TIME_WHEN.includes(b.when) ? "🕒" : "🌤"} ${esc(WHEN_SHORT[b.when] || b.when)}</span>` : b.weather ? '<span class="badge">🌤 weather</span>' : ""}<span class="badge">${esc(KIND_LABEL[b.kind])}</span><span class="spacer"></span><span class="sub">${b.duration.toFixed(1)}s</span></div>
      <div class="sub">${b.cards.map((c) => esc(c.text)).join(" / ")}</div>
      <div class="row"><a class="btn small" href="#/bumper/${b.id}">Edit</a><button class="btn small danger" data-del="${b.id}">Delete</button></div>
    </div>`).join("") || '<div class="empty">No bumpers here.</div>'}`;
  for (const b of shown) {
    const img = $(`[data-thumb="${b.id}"]`);
    const idx = Math.min(b.cards.length - 1, b.cards.length > 1 ? 1 : 0);
    renderCardImg(b, idx).then((u) => (img.src = u)).catch(() => { });
  }
  $$("[data-del]").forEach((x) => (x.onclick = async () => {
    if (!confirm("Delete this bumper?")) return;
    await api("DELETE", "bumpers/" + x.dataset.del); route();
loadStatus();
  }));
}

async function showBumper(id) {
  let b;
  await loadThemes();
  if (id === "new") b = { name: "New bumper", kind: "any", gap: 0.35, music_path: "", cards: [{ text: "you're watching {channel}.", seconds: 3 }],
    style: { bg: "#000000", fg: "#ffffff", font: "regular", size: "medium", align: "center", case: "lower", tag: "[{channel}]", tag_pos: "bottom-right", font_path: "", font_id: "" } };
  else b = (await api("GET", "bumpers")).find((x) => x.id === id);
  if (!b) { view.innerHTML = '<div class="card">Bumper not found.</div>'; return; }
  let sel = 0, playing = null;
  const st = b.style;
  const defMusic = ((await api("GET", "settings").catch(() => ({}))).bumper_music_path || "");
  view.innerHTML = `<div class="row" style="margin-bottom:16px"><a href="#/bumpers" class="btn small">← Bumpers</a>
      <h1 style="margin:0">${id === "new" ? "New bumper" : esc(b.name)}</h1><span class="spacer"></span><button class="btn primary" id="save">Save</button></div>
    <div class="editor"><div class="stack">
      <div class="card"><div class="form">
        <label class="f">Name<input type="text" id="b_name" value="${esc(b.name)}"></label>
        <label class="f">Where it plays<select id="b_kind">${Object.entries(KIND_LABEL).map(([k, l]) => `<option value="${k}" ${b.kind === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="f wide">When it plays<select id="b_when">
          <option value="">${WHEN_LABEL[""]}</option>
          <optgroup label="Time of day">${TIME_WHEN.map((k) => `<option value="${k}" ${b.when === k ? "selected" : ""}>${WHEN_LABEL[k]}</option>`).join("")}</optgroup>
          <optgroup label="Weather (from your weather channel)">${Object.keys(WHEN_SHORT).filter((k) => !TIME_WHEN.includes(k)).map((k) => `<option value="${k}" ${b.when === k ? "selected" : ""}>${WHEN_LABEL[k]}</option>`).join("")}</optgroup></select></label>
      </div></div>
      <div class="card"><h2>Cards</h2><div id="cards"></div>
        <div class="row" style="margin-top:8px"><button class="btn small" id="addcard">+ Add card</button><span class="spacer"></span>
          <label class="f" style="flex-direction:row;align-items:center;gap:8px">Black between cards (s)<input type="number" id="b_gap" min="0" max="3" step="0.05" value="${b.gap}" style="width:80px"></label></div>
        <div class="vars sub" style="margin-top:10px">Insert: ${VARS.map(([v, d]) => `<code data-var="${v}" title="${d}">{${v}}</code>`).join("")}</div>
        <div class="vars sub" style="margin-top:6px">Weather: ${WX_VARS.map(([v, d]) => `<code data-var="${v}" title="${d}">{${v}}</code>`).join("")}
          <br><span>Weather words come from your weather channel. A bumper that uses them is skipped when there's no forecast.</span></div></div>
      <div class="card"><h2>Font</h2><input type="hidden" id="s_fontid" value="${esc(st.font_id || "")}">
        <div class="fontgrid" id="fontgrid"></div>
        <p class="sub">Your own .ttf/.otf files show up here after you drop them in the fonts folder (see Appearance). Or point to any font file under Look.</p></div>
      <div class="card"><h2>Look</h2><div class="form">
        <label class="f">Background<input type="color" id="s_bg" value="${esc(st.bg)}"></label>
        <label class="f">Text<input type="color" id="s_fg" value="${esc(st.fg)}"></label>
        <label class="f">Weight<select id="s_font"><option value="regular">Regular</option><option value="bold" ${st.font === "bold" ? "selected" : ""}>Bold</option></select></label>
        <label class="f">Size<select id="s_size">${["small", "medium", "large", "huge"].map((x) => `<option ${st.size === x ? "selected" : ""}>${x}</option>`).join("")}</select></label>
        <label class="f">Alignment<select id="s_align"><option value="center">Centered</option><option value="left" ${st.align === "left" ? "selected" : ""}>Left</option></select></label>
        <label class="f">Letter case<select id="s_case"><option value="lower">all lowercase</option><option value="asis" ${st.case === "asis" ? "selected" : ""}>As typed</option><option value="upper" ${st.case === "upper" ? "selected" : ""}>ALL CAPS</option></select></label>
        <label class="f">Corner tag<input type="text" id="s_tag" value="${esc(st.tag)}" placeholder="[{channel}]"></label>
        <label class="f">Tag corner<select id="s_tagpos">${["bottom-right", "bottom-left", "top-right", "top-left"].map((x) => `<option ${st.tag_pos === x ? "selected" : ""}>${x}</option>`).join("")}</select></label>
        <label class="f wide">Or a font file (any .ttf/.otf on the Broadcast server — overrides the font above)<input type="text" id="s_fontpath" value="${esc(st.font_path || "")}" placeholder="auto"></label>
        <label class="f wide">Music (file or folder on the Broadcast server, optional)<input type="text" id="b_music" value="${esc(b.music_path || "")}"
          placeholder="${defMusic ? "default: " + esc(defMusic) : "default: the channel's music, or silence"}">
          <span class="sub">${defMusic ? `Leave empty to use the default bumper music (<a href="#/bumpers">change</a>).` : `Leave empty to use the channel's music. Set a default for all bumpers on the <a href="#/bumpers">Bumpers page</a>.`}</span></label>
      </div></div>
    </div><div class="stack"><div class="card"><h2>Preview</h2>
      <div class="preview"><img id="pimg" alt=""></div>
      <div class="row" style="margin-top:10px"><button class="btn small" id="play">▶ Play</button><span class="sub" id="pinfo"></span></div>
      <p class="sub">Sample values: show “Cosmic Diner”, next “Midnight Mysteries”; weather is live when your weather channel has a forecast. On air, the real titles are filled in.</p></div></div></div>`;

  const collect = () => ({ id: id === "new" ? undefined : b.id, name: $("#b_name").value.trim() || "Bumper", kind: $("#b_kind").value,
    when: $("#b_when").value, pack: b.pack,
    gap: +$("#b_gap").value || 0, music_path: $("#b_music").value.trim(), cards: b.cards,
    style: { bg: $("#s_bg").value, fg: $("#s_fg").value, font: $("#s_font").value, size: $("#s_size").value, align: $("#s_align").value,
      case: $("#s_case").value, tag: $("#s_tag").value, tag_pos: $("#s_tagpos").value, font_path: $("#s_fontpath").value.trim(), font_id: $("#s_fontid").value } });
  let deb;
  const preview = () => { clearTimeout(deb); deb = setTimeout(async () => {
    try { $("#pimg").src = await renderCardImg(collect(), sel); } catch (e) { toast(e.message, true); }
    const total = b.cards.reduce((a, c) => a + (+c.seconds || 0), 0) + (+$("#b_gap").value || 0) * (b.cards.length + 1);
    $("#pinfo").textContent = `Card ${sel + 1} of ${b.cards.length} · total ${total.toFixed(1)}s`;
  }, 250); };
  const drawCards = () => {
    $("#cards").innerHTML = b.cards.map((c, i) => `<div class="cardrow ${i === sel ? "sel" : ""}" data-i="${i}">
      <div class="n">${i + 1}</div><textarea data-t="${i}" rows="2">${esc(c.text)}</textarea>
      <input type="number" data-s="${i}" min="0.5" max="30" step="0.5" value="${c.seconds}" title="seconds on screen">
      <div class="tools"><button class="btn small" data-up="${i}" title="Move up">↑</button><button class="btn small" data-rm="${i}" title="Remove">×</button></div></div>`).join("");
    $$("[data-t]").forEach((t) => {
      t.oninput = () => { b.cards[+t.dataset.t].text = t.value; preview(); };
      t.onfocus = () => { sel = +t.dataset.t; $$(".cardrow").forEach((r) => r.classList.toggle("sel", +r.dataset.i === sel)); preview(); };
    });
    $$("[data-s]").forEach((t) => (t.oninput = () => { b.cards[+t.dataset.s].seconds = +t.value || 3; preview(); }));
    $$("[data-rm]").forEach((x) => (x.onclick = () => { if (b.cards.length > 1) { b.cards.splice(+x.dataset.rm, 1); sel = Math.min(sel, b.cards.length - 1); drawCards(); preview(); } }));
    $$("[data-up]").forEach((x) => (x.onclick = () => { const i = +x.dataset.up; if (i > 0) { [b.cards[i - 1], b.cards[i]] = [b.cards[i], b.cards[i - 1]]; sel = i - 1; drawCards(); preview(); } }));
  };
  let lastFocus = null;
  document.addEventListener("focusin", (e) => { if (e.target.matches?.("[data-t], #s_tag")) lastFocus = e.target; });
  $$("[data-var]").forEach((c) => (c.onclick = () => {
    const t = lastFocus || $(`[data-t="${sel}"]`); if (!t) return;
    const v = `{${c.dataset.var}}`, p = t.selectionStart ?? t.value.length;
    t.value = t.value.slice(0, p) + v + t.value.slice(t.selectionEnd ?? p); t.dispatchEvent(new Event("input")); t.focus();
  }));
  $("#addcard").onclick = () => { b.cards.push({ text: "", seconds: 3 }); sel = b.cards.length - 1; drawCards(); preview(); $(`[data-t="${sel}"]`).focus(); };
  const drawFonts = () => {
    const cur = $("#s_fontid").value, bg = $("#s_bg").value, fg = $("#s_fg").value;
    const fonts = [{ id: "", name: "System font", css: "system-ui, sans-serif" }].concat((THEMES?.fonts || []).filter((f) => f.kind !== "clock" && f.id !== "system"));
    const caseOf = (t) => $("#s_case").value === "upper" ? t.toUpperCase() : $("#s_case").value === "lower" ? t.toLowerCase() : t;
    $("#fontgrid").innerHTML = fonts.map((f) => `<button type="button" class="fontpick ${cur === f.id ? "on" : ""}" data-font="${esc(f.id)}" title="${esc(f.desc || "")}">
      <span class="fp-sample" style="font-family:${f.css};background:${esc(bg)};color:${esc(fg)};font-weight:${$("#s_font").value === "bold" ? 700 : 400}">${esc(caseOf("You're watching."))}</span>
      <span class="fp-name">${esc(f.name)}</span></button>`).join("");
    $$("[data-font]", $("#fontgrid")).forEach((x) => (x.onclick = () => { $("#s_fontid").value = x.dataset.font; drawFonts(); preview(); }));
  };
  $$("#s_bg, #s_fg, #s_font, #s_case").forEach((x) => x.addEventListener("input", drawFonts));
  drawFonts();
  $$("#s_bg, #s_fg, #s_fontid, #s_font, #s_size, #s_align, #s_case, #s_tag, #s_tagpos, #s_fontpath, #b_gap").forEach((x) => (x.oninput = x.onchange = preview));
  $("#play").onclick = async () => {
    if (playing) { clearTimeout(playing); playing = null; $("#play").textContent = "▶ Play"; return; }
    $("#play").textContent = "■ Stop";
    const data = collect(), urls = await Promise.all(data.cards.map((_, i) => renderCardImg(data, i)));
    const gap = data.gap * 1000; let i = 0;
    const step = () => {
      if (i >= urls.length) { playing = null; $("#play").textContent = "▶ Play"; preview(); return; }
      $("#pimg").src = ""; $("#pimg").style.visibility = "hidden";
      playing = setTimeout(() => { $("#pimg").style.visibility = "visible"; $("#pimg").src = urls[i];
        playing = setTimeout(step, data.cards[i++].seconds * 1000); }, gap);
    };
    step();
  };
  $("#save").onclick = async () => {
    try { const saved = await api("POST", "bumpers", collect()); toast("Saved"); if (id === "new") location.hash = "#/bumper/" + saved.id; }
    catch (e) { toast(e.message, true); }
  };
  drawCards(); preview();
}

// --------------------------------------------------------------------------- guide
async function showGuide() {
  const g = await api("GET", "guide?hours=3");
  const span = g.end - g.start, pct = (t) => ((Math.max(g.start, Math.min(g.end, t)) - g.start) / span) * 100;
  const slots = []; for (let t = g.start; t < g.end; t += 1800) slots.push(t);
  const rows = g.channels.filter((c) => c.type !== "guide").map((c) => `<div class="gr">
      <div class="cc"><span class="n">${esc(c.number)}</span><img src="${c.logo}" alt=""><span>${esc(c.name)}</span></div>
      <div class="track">${c.entries.filter((e) => e.end > g.start && e.start < g.end).map((e) => {
        const cur = e.start <= g.now && g.now < e.end;
        return `<div class="prog ${cur ? "cur" : ""}" style="left:${pct(e.start)}%;width:calc(${pct(e.end) - pct(e.start)}% - 3px)" title="${esc(e.title + (e.subtitle ? " — " + e.subtitle : "") + "\n" + fmtTime(e.start) + "–" + fmtTime(e.end) + "\n\n" + (e.overview || ""))}">
          ${e.start < g.start ? "◀ " : ""}<b>${esc(e.title)}</b><br><span class="s">${esc(e.subtitle || "")}</span></div>`;
      }).join("")}</div></div>`).join("");
  view.innerHTML = `<div class="row" style="margin-bottom:16px"><h1 style="margin:0">What's on</h1><span class="spacer"></span><span class="sub">${fmtDay(g.now)}</span></div>
    <div class="eguide"><div class="hdr"><div class="cc">Channel</div><div class="track">${slots.map((t) => `<div class="slot" style="left:${pct(t)}%">${fmtTime(t)}</div>`).join("")}
      <div class="nowline" style="left:${pct(g.now)}%"></div></div></div>${rows || '<div class="empty">No channels yet.</div>'}</div>`;
  timer = setInterval(() => { if (!document.hidden) showGuide(); }, 60000);
}

// --------------------------------------------------------------------------- appearance
async function showAppearance() {
  const [TH, s] = await Promise.all([loadThemes(true), api("GET", "settings")]);
  let cur = s.theme || "barnes", uiFont = s.ui_font || "theme", saved = { cur, uiFont };
  const T = () => TH.themes.find((t) => t.id === cur) || TH.themes[0];
  view.innerHTML = `<div class="row" style="margin-bottom:16px"><h1 style="margin:0">Appearance</h1><span class="spacer"></span>
      <span class="sub" id="unsaved" style="display:none;color:var(--accent)">Previewing — not saved yet</span>
      <button class="btn" id="revert" style="display:none">Revert</button><button class="btn primary" id="save">Save</button></div>
    <div class="stack">
    <div class="card" id="branding"><h2>Branding</h2>
      <p class="sub" style="margin-top:0">Your station's name and logos, everywhere: the guide and weather channels, Up Next cards, bumpers' <code>{station}</code>,
        the TV page and remote, this page, browser and phone icons, and the name Jellyfin shows for the tuner. Leave everything as it is for the Barnes look.</p>
      <div class="form">
        <label class="f">Station name<input type="text" id="br_name" value="${esc(s.station_name || BRAND.name)}" maxlength="80"></label>
        <label class="f">Short name (app name, tab title)<input type="text" id="br_short" value="${esc(s.station_short || "")}" placeholder="${esc(BRAND.short)}" maxlength="30"></label>
        <label class="f">Brand colour (app icon &amp; TV app background)<input type="color" id="br_color" value="${esc(BRAND.color || "#0b1a4a")}"></label>
        <label class="check wide"><input type="checkbox" id="br_recolor" ${BRAND.recolor ? "checked" : ""}> Recolour the logos to match each theme
          <span class="sub">(for one-colour logos on a transparent background; untick for full-colour logos)</span></label>
      </div>
      <div class="brandgrid">
        ${[["wordmark", "Wide logo", "Guide header, TV page start screen, welcome screen. A wide PNG with a transparent background works best."],
           ["mark", "Small logo", "Admin header, Up Next cards, weather header, the remote. Roughly square or a little wide."],
           ["icon", "App icon", "Browser tab, phone home screen and the TV app icon. Square. If you don't upload one, it's made from the small logo on the brand colour."]]
          .map(([k, l, d]) => `<div class="brandslot"><b>${l}</b><div class="brandprev ${k === "icon" ? "sq" : ""}"><img data-brandimg="${k}" class="${k === "icon" ? "" : "brandart"}" alt=""></div>
            <div class="sub">${d}</div><input type="file" accept="image/*" data-brandfile="${k}" style="display:none">
            <div class="row" style="gap:6px"><button class="btn small" data-brandup="${k}">Upload…</button>
              <button class="btn small" data-brandrm="${k}" ${BRAND.custom && BRAND.custom[k] ? "" : "disabled"}>Use default</button></div></div>`).join("")}
      </div>
      <div class="row" style="margin-top:12px"><button class="btn primary" id="br_save">Save branding</button>
        <a class="btn" href="/api/brand/tvapp-kit.zip" title="Icon, banner and name for building the Android TV app with your branding">⬇ TV app branding kit</a>
        <span class="spacer"></span><button class="btn small danger" id="br_reset">Back to the Barnes default</button></div></div>
    <div class="card"><h2>Station theme</h2>
      <p class="sub" style="margin-top:0">One look for the guide channel, the “Up Next” and standby cards, the Up Next banner, this admin page, the TV page and the phone remote.
        Each channel can pick a different theme in its own settings.</p>
      <div class="themes" id="themes">${TH.themes.map((t) => `<div class="theme" role="button" tabindex="0" data-theme="${t.id}">
        <div class="sw">${t.swatch.map((c) => `<i style="background:${c}"></i>`).join("")}</div>
        <b style="font-family:${fontCss(t.fonts.display)}">${esc(t.name)}${t.custom ? ' <span class="badge">yours</span>' : ""}</b><small>${esc(t.desc || "")}</small>
        <span class="row" style="gap:6px;margin-top:auto">${t.custom ? `<a class="btn small" href="#/theme/${t.id}" data-edit>✎ Edit</a>` : ""}<a class="btn small" href="#/theme/new~${t.id}" data-edit>⧉ Copy &amp; customise</a></span></div>`).join("")}
        <a class="theme" href="#/theme/new~${esc(s.theme || "barnes")}" style="text-decoration:none;align-items:center;justify-content:center;min-height:150px;border-style:dashed">
          <b style="font-size:34px;line-height:1">＋</b><b>Create a theme</b><small>Start from the current theme and change anything: colours, fonts, boxes, decorations.</small></a></div></div>
    <div class="card"><h2>Preview: <span id="pvname"></span></h2>
      <div class="prevpair"><div><div class="sub">Guide channel</div><img id="pv_guide" alt=""></div><div><div class="sub">Up Next card</div><img id="pv_slate" alt=""></div></div></div>
    <div class="card"><h2>Fonts</h2><div class="form">
      <label class="f">Admin page, TV page &amp; remote<select id="ui_font">${fontOptions(uiFont, T().fonts.ui)}</select></label>
      <div class="fontsample wide" id="ui_sample">The quick brown fox · 8:30 PM · となりのアニメ</div></div>
      <p class="sub">Guide channel fonts are set on the guide channel itself (Channels → TV Guide). Clock fonts are per channel, under On-screen graphics → Clock.</p>
      <h3>Font library</h3>
      <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(260px,1fr))">${TH.fonts.filter((f) => f.id !== "system").map((f) =>
        `<div class="subcard" style="margin:0"><div style="font-family:${f.css};font-size:26px;white-space:nowrap;overflow:hidden">${f.kind === "clock" ? "12:34" : f.cjk ? "Aa 8:30 あア字" : "Aa 8:30 Rewind"}</div>
         <b>${esc(f.name)}</b><div class="sub">${esc(f.desc)}</div></div>`).join("")}</div>
      <p class="sub">Add your own: drop <b>.ttf</b> or <b>.otf</b> files into <code>${esc(TH.fonts_folder)}</code>, then reload this page. They appear under “Your fonts” in every font menu.</p></div>
    </div>`;
  // ---- branding
  const brandImgs = () => $$("[data-brandimg]").forEach((im) => {
    const k = im.dataset.brandimg;
    im.src = (k === "icon" ? "/static/icon-192.png" : `/brand/${k}.png`) + `?v=${BRAND.version}&t=${Date.now()}`;
  });
  const brandRefresh = async (b) => {
    Object.assign(BRAND, b);
    $("#station").textContent = BRAND.name;
    $(".top .brand img").src = `/brand/mark.png?v=${BRAND.version}`;
    $$("[data-brandrm]").forEach((x) => (x.disabled = !(BRAND.custom && BRAND.custom[x.dataset.brandrm])));
    $("#br_recolor").checked = !!BRAND.recolor;
    brandImgs(); apply();
  };
  brandImgs();
  $$("[data-brandup]").forEach((b) => (b.onclick = () => $(`[data-brandfile="${b.dataset.brandup}"]`).click()));
  $$("[data-brandfile]").forEach((f) => (f.onchange = async () => {
    const file = f.files[0]; if (!file) return;
    try { brandRefresh(await api("POST", "brand/" + f.dataset.brandfile, undefined, file)); toast("Logo updated"); } catch (e) { toast(e.message, true); }
    f.value = "";
  }));
  $$("[data-brandrm]").forEach((b) => (b.onclick = async () => {
    try { brandRefresh(await api("DELETE", "brand/" + b.dataset.brandrm)); toast("Back to the default artwork"); } catch (e) { toast(e.message, true); }
  }));
  $("#br_save").onclick = async () => {
    const name = $("#br_name").value.trim();
    try {
      await api("POST", "settings", { station_name: name === "Barnes Television Broadcasting System" ? "" : name, station_short: $("#br_short").value.trim(),
        brand_color: $("#br_color").value, brand_recolor: $("#br_recolor").checked });
      brandRefresh(await api("GET", "brand")); toast("Branding saved");
    } catch (e) { toast(e.message, true); }
  };
  $("#br_reset").onclick = async () => {
    if (!confirm("Remove your logos and name and go back to the Barnes branding?")) return;
    try { const b = await api("POST", "brand/reset"); $("#br_name").value = b.name; $("#br_short").value = ""; $("#br_color").value = b.color; brandRefresh(b); toast("Barnes branding restored"); }
    catch (e) { toast(e.message, true); }
  };
  const apply = () => {
    $$("[data-theme]").forEach((b) => b.classList.toggle("on", b.dataset.theme === cur));
    $("#themecss").href = `/theme.css?theme=${cur}&font=${encodeURIComponent($("#ui_font").value)}`;
    $("#pvname").textContent = T().name;
    $("#pv_guide").src = `/api/themes/${cur}/guide.jpg?t=${Date.now()}`;
    $("#pv_slate").src = `/api/themes/${cur}/slate.jpg?t=${Date.now()}`;
    sampleFont($("#ui_sample"), resolveFont($("#ui_font").value, T().fonts.ui));
    const changed = cur !== saved.cur || $("#ui_font").value !== saved.uiFont;
    $("#unsaved").style.display = $("#revert").style.display = changed ? "" : "none";
    $("#save").classList.toggle("dirty", changed);
  };
  $$("[data-edit]").forEach((a) => a.addEventListener("click", (e) => e.stopPropagation()));
  $$("[data-theme]").forEach((b) => (b.onclick = () => {
    cur = b.dataset.theme;
    const v = $("#ui_font").value; $("#ui_font").innerHTML = fontOptions(v, T().fonts.ui);
    apply();
  }));
  $("#ui_font").onchange = apply;
  $("#revert").onclick = () => { cur = saved.cur; $("#ui_font").innerHTML = fontOptions(saved.uiFont, T().fonts.ui); apply(); };
  $("#save").onclick = async () => {
    try {
      await api("POST", "settings", { theme: cur, ui_font: $("#ui_font").value });
      saved = { cur, uiFont: $("#ui_font").value }; THEMES = null; await loadThemes();
      $("#themecss").href = `/theme.css?v=${Date.now()}`; apply();
      toast("Theme saved — the guide channel and TV pages update within a few seconds");
    } catch (e) { toast(e.message, true); }
  };
  leaveGuard = (silent) => {
    const changed = cur !== saved.cur || $("#ui_font")?.value !== saved.uiFont;
    if (!changed) return true;
    if (silent || confirm("Leave without saving the new theme?")) { $("#themecss").href = `/theme.css?v=${Date.now()}`; return true; }
    return false;
  };
  apply();
}


// --------------------------------------------------------------------------- theme builder
const COLOR_GROUPS = [
  ["Guide channel", [["bg", "Background"], ["head1", "Header (top)"], ["head2", "Header (bottom)"], ["chan", "Channel column"],
    ["chan_text", "Channel names"], ["num", "Channel numbers"], ["filler", "Station-break boxes"], ["cell_border", "Box borders"],
    ["cell_text", "Programme text"], ["timebar", "Time bar"], ["timebar_text", "Time bar text"], ["spot_bg", "Spotlight panel"],
    ["spot_border", "Spotlight border"], ["track", "Progress track"], ["now", "“Now” line"]]],
  ["Text & highlights (everywhere)", [["text", "Main text"], ["muted", "Secondary text"], ["accent", "Highlight"],
    ["accent2", "Second highlight (Up Next banner, selections)"], ["on_accent", "Text on highlight buttons"]]],
  ["Admin page, TV page & remote", [["page", "Page background"], ["panel", "Cards"], ["panel2", "Buttons & raised areas"],
    ["line", "Borders"], ["input", "Text boxes"]]],
];
const CELL_LABELS = { flat: "Flat", bevel: "Bevelled 3-D", round: "Rounded", cut: "Cut corners", deco: "Double frame (art deco)",
  chunky: "Chunky outline + shadow", glow: "Outlined (good with glow)", epg: "Listings grid", gloss: "Glossy", outline: "Thin outline", pixel: "Pixel" };
const DECO_LABELS = { none: "None", stripes: "Diagonal stripes", vhs: "Rainbow bars + scanlines", rainbow70s: "’70s rainbow",
  circuit: "Circuit grid + corner brackets", sunburst: "Sunburst + stepped frame", memphis: "Memphis shapes (uses your box colours)",
  outrun: "Sunset + neon grid", teletext: "Teletext mosaic", tokyo: "Red sun + pinstripes", bubbles: "Bubbles + grass",
  crt: "CRT scanlines + vignette", starburst: "Atomic starbursts", pixel: "Pixel stars + mountains" };
const PAGE_STYLE_LABELS = { soft: "Soft (rounded cards)", square: "Square corners", chunky: "Chunky outlines + shadows", glow: "Glowing edges", glass: "Frosted glass" };
const PAGE_PATTERN_LABELS = { none: "None", grid: "Grid", dots: "Dots", scanlines: "Scanlines", stripes: "Stripes" };
const FONT_ROLE_LABELS = [["ui", "Admin, TV page & remote text"], ["display", "Headings"], ["guide", "Guide listings"],
  ["guide_display", "Guide clock & channel numbers"], ["clock", "On-screen clock (channels set to “theme default”)"]];

async function apiImage(path, body) {
  const r = await fetch("/api/" + path, { method: "POST", headers: { "Content-Type": "application/json", "X-Unlock": unlockTok() }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error((await r.text()).slice(0, 200));
  return URL.createObjectURL(await r.blob());
}

async function showThemeBuilder(arg) {
  await loadThemes(true);
  const isNew = !arg || arg.startsWith("new");
  const from = isNew ? (arg || "new~barnes").split("~")[1] || "barnes" : arg;
  let t = await api("GET", `themes/${from}/spec`);
  if (isNew) { t = { ...t, id: "", desc: "" }; if (!t.name.includes("(copy)")) t.name += " (copy)"; }
  const colorInput = (k, label) => `<label class="f">${label}<input type="color" data-c="${k}" value="${esc(t.c[k])}"></label>`;
  view.innerHTML = `<div class="row" style="margin-bottom:16px"><a href="#/appearance" class="btn small">← Appearance</a>
      <h1 style="margin:0">${isNew ? "New theme" : "Edit theme"}</h1><span class="spacer"></span>
      ${!isNew ? '<button class="btn danger" id="tb_delete">Delete</button>' : ""}
      <button class="btn" id="tb_save">Save</button><button class="btn primary" id="tb_use">Save &amp; use for the station</button></div>
    <div class="editor"><div class="stack">
      <div class="card"><div class="form">
        <label class="f">Name<input type="text" id="tb_name" value="${esc(t.name)}" maxlength="40"></label>
        <label class="f">Start over from<select id="tb_base"><option value="">—</option>${TH_LIST().map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select></label>
        <label class="f wide">Description<input type="text" id="tb_desc" value="${esc(t.desc || "")}" maxlength="160" placeholder="optional"></label>
      </div></div>
      ${COLOR_GROUPS.map(([title, keys], gi) => `<div class="card"><h2>${title}</h2><div class="form">
        ${gi === 0 ? `<div class="f wide"><span class="sub">Programme boxes (they alternate in this order — 1 to 4 colours)</span><div class="row" id="tb_cells"></div></div>` : ""}
        ${keys.map(([k, l]) => colorInput(k, l)).join("")}</div></div>`).join("")}
      <div class="card"><h2>Fonts</h2><div class="form">${FONT_ROLE_LABELS.map(([r, l]) =>
        `<label class="f">${l}<select data-font="${r}">${fontOptions(t.fonts[r], undefined, { clock: r === "clock" || r === "guide_display" })}</select></label>`).join("")}</div></div>
      <div class="card"><h2>Style</h2><div class="form">
        <label class="f">Programme boxes<select id="tb_cell">${Object.entries(CELL_LABELS).map(([k, l]) => `<option value="${k}" ${t.cell === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="f">Header decoration<select id="tb_deco">${Object.entries(DECO_LABELS).map(([k, l]) => `<option value="${k}" ${t.deco === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="f">Corner rounding: <span id="tb_radius_v">${t.radius}</span><input type="range" id="tb_radius" min="0" max="30" value="${t.radius}"></label>
        <label class="f">Space between boxes: <span id="tb_gap_v">${t.gap}</span><input type="range" id="tb_gap" min="0" max="12" value="${t.gap}"></label>
        <label class="f">Station artwork (logo) colour<select id="tb_brand"><option value="">Original white</option><option value="tint">Tinted…</option><option value="text">Text instead of logo (teletext style)</option></select></label>
        <label class="f" id="tb_brandc_l">Logo tint<input type="color" id="tb_brandc" value="${esc(/^#/.test(t.c.brand || "") ? t.c.brand : "#ffffff")}"></label>
        <label class="check"><input type="checkbox" id="tb_glow" ${t.glow ? "checked" : ""}> Neon glow on text</label>
        <label class="check"><input type="checkbox" id="tb_scan" ${t.body === "scanlines" ? "checked" : ""}> Scanlines over the listings</label>
        <label class="check"><input type="checkbox" id="tb_upper" ${t.upper ? "checked" : ""}> ALL CAPS titles</label>
        <label class="check"><input type="checkbox" id="tb_genre" ${t.genre_colors ? "checked" : ""}> Colour boxes by genre (Japanese-listings style)</label>
        <label class="check wide"><input type="checkbox" id="tb_light" ${t.light ? "checked" : ""}> Light theme <span class="sub">(dark logo artwork and light panels on the TV page)</span></label>
        <label class="f">Page style<select id="tb_pstyle">${Object.entries(PAGE_STYLE_LABELS).map(([k, l]) => `<option value="${k}" ${t.page_style === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="f">Page background pattern<select id="tb_ppat">${Object.entries(PAGE_PATTERN_LABELS).map(([k, l]) => `<option value="${k}" ${t.page_pattern === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      </div></div>
    </div><div class="stack" style="position:sticky;top:80px">
      <div class="card"><h2>Preview</h2>
        <div class="sub">Guide channel</div><div class="preview"><img id="tb_pg" alt=""></div>
        <div class="sub" style="margin-top:10px">Up Next card</div><div class="preview"><img id="tb_ps" alt=""></div>
        <label class="check" style="margin-top:10px"><input type="checkbox" id="tb_live" checked> Also preview on this page</label>
        <p class="sub">Previews update a moment after each change. Nothing is on air until you save.</p></div>
    </div></div>`;
  function TH_LIST() { return THEMES.themes; }
  let cells = [...t.c.cells];
  const drawCells = () => {
    $("#tb_cells").innerHTML = cells.map((c, i) => `<input type="color" data-cell="${i}" value="${c}" style="width:64px">`).join("") +
      (cells.length < 4 ? '<button class="btn small" id="tb_addcell">＋</button>' : "") + (cells.length > 1 ? '<button class="btn small" id="tb_rmcell">−</button>' : "");
    $$("[data-cell]").forEach((x) => (x.oninput = () => { cells[+x.dataset.cell] = x.value; changed(); }));
    if ($("#tb_addcell")) $("#tb_addcell").onclick = () => { cells.push(cells[cells.length - 1]); drawCells(); changed(); };
    if ($("#tb_rmcell")) $("#tb_rmcell").onclick = () => { cells.pop(); drawCells(); changed(); };
  };
  $("#tb_brand").value = t.c.brand === "text" ? "text" : /^#/.test(t.c.brand || "") ? "tint" : "";
  const brandVis = () => ($("#tb_brandc_l").style.display = $("#tb_brand").value === "tint" ? "" : "none");
  const collect = () => {
    const c = {}; $$("[data-c]").forEach((x) => (c[x.dataset.c] = x.value)); c.cells = [...cells];
    const b = $("#tb_brand").value; if (b === "text") c.brand = "text"; else if (b === "tint") c.brand = $("#tb_brandc").value;
    const fonts = {}; $$("[data-font]").forEach((x) => (fonts[x.dataset.font] = x.value));
    return { id: isNew ? "" : t.id, base: t.base, name: $("#tb_name").value.trim(), desc: $("#tb_desc").value.trim(), c, fonts,
      cell: $("#tb_cell").value, deco: $("#tb_deco").value, radius: +$("#tb_radius").value, gap: +$("#tb_gap").value,
      glow: $("#tb_glow").checked, body: $("#tb_scan").checked ? "scanlines" : "", upper: $("#tb_upper").checked,
      genre_colors: $("#tb_genre").checked, light: $("#tb_light").checked, page_style: $("#tb_pstyle").value, page_pattern: $("#tb_ppat").value };
  };
  let deb, seq = 0, dirty = false;
  const livecss = document.createElement("style"); livecss.id = "tb_livecss"; document.head.appendChild(livecss);
  const refresh = async () => {
    if (!$("#tb_name")) return;          // left the page meanwhile
    const my = ++seq, spec = collect();
    $("#tb_radius_v").textContent = spec.radius; $("#tb_gap_v").textContent = spec.gap; brandVis();
    try {
      const [g, sl] = await Promise.all([apiImage("themes/preview/guide.jpg", spec), apiImage("themes/preview/slate.jpg", spec)]);
      if (my !== seq) return;
      $("#tb_pg").src = g; $("#tb_ps").src = sl;
      if ($("#tb_live").checked) {
        const r = await fetch("/api/themes/preview.css", { method: "POST", headers: { "Content-Type": "application/json", "X-Unlock": unlockTok() }, body: JSON.stringify(spec) });
        if (r.ok && my === seq) livecss.textContent = await r.text();
      } else livecss.textContent = "";
    } catch (e) { toast(e.message, true); }
  };
  const changed = () => { dirty = true; clearTimeout(deb); deb = setTimeout(refresh, 450); };
  ["input", "change"].forEach((ev) => $(".editor").addEventListener(ev, (e) => { if (e.target.id !== "tb_base") changed(); }));
  $("#tb_base").onchange = async () => {
    const b = $("#tb_base").value; if (!b) return;
    if (!confirm("Replace every setting below with that theme's? (The name stays.)")) { $("#tb_base").value = ""; return; }
    const name = $("#tb_name").value;
    const n = await api("GET", `themes/${b}/spec`);
    t = { ...n, id: t.id, name }; skipRoute = false;
    cells = [...t.c.cells];
    $$("[data-c]").forEach((x) => (x.value = t.c[x.dataset.c]));
    $$("[data-font]").forEach((x) => (x.value = t.fonts[x.dataset.font]));
    $("#tb_cell").value = t.cell; $("#tb_deco").value = t.deco; $("#tb_radius").value = t.radius; $("#tb_gap").value = t.gap;
    $("#tb_glow").checked = t.glow; $("#tb_scan").checked = t.body === "scanlines"; $("#tb_upper").checked = t.upper;
    $("#tb_genre").checked = t.genre_colors; $("#tb_light").checked = t.light; $("#tb_pstyle").value = t.page_style; $("#tb_ppat").value = t.page_pattern;
    $("#tb_brand").value = t.c.brand === "text" ? "text" : /^#/.test(t.c.brand || "") ? "tint" : "";
    if (/^#/.test(t.c.brand || "")) $("#tb_brandc").value = t.c.brand;
    $("#tb_base").value = ""; drawCells(); changed();
  };
  const save = async (use) => {
    try {
      const spec = await api("POST", "themes/custom", Object.assign(collect(), { use }));
      dirty = false; THEMES = null; livecss.remove(); clearTimeout(deb); seq++;
      toast(use ? `“${spec.name}” saved and on the air` : `“${spec.name}” saved`);
      $("#themecss").href = `/theme.css?v=${Date.now()}`;
      location.hash = use ? "#/appearance" : "#/theme/" + spec.id;
    } catch (e) { toast(e.message, true); }
  };
  $("#tb_save").onclick = () => save(false);
  $("#tb_use").onclick = () => save(true);
  if ($("#tb_delete")) $("#tb_delete").onclick = async () => {
    if (!confirm(`Delete “${t.name}”? Channels using it go back to the station theme.`)) return;
    try { await api("DELETE", "themes/custom/" + t.id); dirty = false; livecss.remove(); $("#themecss").href = `/theme.css?v=${Date.now()}`; location.hash = "#/appearance"; }
    catch (e) { toast(e.message, true); }
  };
  leaveGuard = (silent) => {
    if (dirty && (silent || !confirm("Leave without saving this theme?"))) return false;
    livecss.remove(); clearTimeout(deb); seq++; return true;
  };
  drawCells(); refresh();
}

// --------------------------------------------------------------------------- settings
async function showSettings() {
  const [s, st] = await Promise.all([api("GET", "settings"), loadStatus()]);
  const enc = [["libx264", "CPU (libx264) — works everywhere"], ["h264_nvenc", "NVIDIA (NVENC)"], ["h264_qsv", "Intel Quick Sync (QSV)"],
    ["h264_amf", "AMD (AMF) — Windows"], ["h264_vaapi", "VAAPI — Linux Intel/AMD"], ["h264_videotoolbox", "Apple VideoToolbox"]];
  const maps = (s.path_mappings || []).map((m) => `${m.from} => ${m.to}`).join("\n");
  view.innerHTML = `<h1>Settings</h1><div class="stack">
  <div class="card"><h2>Jellyfin server</h2><div class="form">
    <label class="f">Jellyfin URL<input type="url" id="jellyfin_url" value="${esc(s.jellyfin_url)}" placeholder="http://192.168.1.10:8096"></label>
    <label class="f">API key<input type="password" id="jellyfin_api_key" value="${esc(s.jellyfin_api_key)}" placeholder="Dashboard → API Keys → +"></label>
    <label class="f">Browse library as user<select id="jellyfin_user_id"><option value="">First administrator</option>
      ${s.jellyfin_user_id ? `<option value="${esc(s.jellyfin_user_id)}" selected>${esc(s.jellyfin_user_id)}</option>` : ""}</select></label>
    <div class="row wide"><button class="btn" id="test">Test connection</button><span id="testres" class="sub"></span></div>
  </div><p class="sub">Create the key in Jellyfin: <b>Dashboard → API Keys → +</b>. Picking a user applies that user's parental controls and library access to every channel.</p></div>

  <div class="card"><h2>Station</h2><div class="form">
    <p class="sub wide" style="margin:0">Station name and logos: <a href="#/appearance">Appearance → Branding</a>.</p>
    <label class="f">Address Jellyfin uses to reach this app<input type="url" id="public_url" value="${esc(s.public_url)}" placeholder="auto: ${esc(st?.base_url || "")}"></label>
    <label class="f">Admin password (optional)<input type="password" id="admin_password" value="${esc(s.admin_password)}" placeholder="none"></label>
    <label class="f">Days of schedule to plan ahead<input type="number" id="schedule_days" min="1" max="14" value="${s.schedule_days}"></label>
    <label class="f">Guide data hours (XMLTV)<input type="number" id="epg_hours" min="6" max="168" value="${s.epg_hours}"></label>
    <label class="f">Re-scan libraries every (hours)<input type="number" id="library_refresh_hours" min="1" value="${s.library_refresh_hours}"></label>
    <label class="f">Stop a channel after nobody watches for (s)<input type="number" id="idle_timeout_seconds" min="5" value="${s.idle_timeout_seconds}"></label>
  </div></div>

  <div class="card"><h2>Video</h2><div class="form">
    <label class="f">Resolution<select id="resolution">${["854x480", "1280x720", "1920x1080"].map((r) => `<option ${s.resolution === r ? "selected" : ""}>${r}</option>`).join("")}</select></label>
    <label class="f">Frame rate<select id="framerate">${[24, 25, 30, 50, 60].map((r) => `<option ${+s.framerate === r ? "selected" : ""}>${r}</option>`).join("")}</select></label>
    <label class="f">Encoder<select id="video_encoder">${enc.map(([v, l]) => `<option value="${v}" ${s.video_encoder === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
    <label class="f">Speed preset<select id="encoder_preset">${["ultrafast", "superfast", "veryfast", "faster", "fast", "medium"].map((p) => `<option ${s.encoder_preset === p ? "selected" : ""}>${p}</option>`).join("")}</select></label>
    <label class="f">Video bitrate (kbps)<input type="number" id="video_bitrate_kbps" min="500" value="${s.video_bitrate_kbps}"></label>
    <label class="f">Audio bitrate (kbps)<input type="number" id="audio_bitrate_kbps" min="64" value="${s.audio_bitrate_kbps}"></label>
    <label class="f">VAAPI device (Linux)<input type="text" id="vaapi_device" value="${esc(s.vaapi_device)}"></label>
    <label class="check"><input type="checkbox" id="deinterlace" ${s.deinterlace ? "checked" : ""}> Deinterlace old TV recordings</label>
    <label class="check"><input type="checkbox" id="tonemap_hdr" ${s.tonemap_hdr ? "checked" : ""}> Convert HDR to SDR</label>
  </div><p class="sub">Each channel that someone is watching uses one encoder. A modern CPU handles a few 720p channels; use your GPU for more.</p></div>

  <div class="card"><h2>Media access &amp; tools</h2><div class="form">
    <label class="f">How to read media<select id="media_access"><option value="stream">Stream from Jellyfin (works anywhere)</option>
      <option value="direct" ${s.media_access === "direct" ? "selected" : ""}>Read files directly (same machine / shared drive — faster)</option></select></label>
    <label class="f wide">Path mappings for direct mode, one per line: <code>Jellyfin path =&gt; local path</code>
      <textarea id="path_mappings" rows="3" placeholder="/media => \\\\NAS\\media">${esc(maps)}</textarea></label>
    <label class="f">ffmpeg path<input type="text" id="ffmpeg_path" value="${esc(s.ffmpeg_path)}" placeholder="auto"></label>
    <label class="f">Font<input type="text" id="font_path" value="${esc(s.font_path)}" placeholder="auto"></label>
    <label class="f">Bold font<input type="text" id="font_bold_path" value="${esc(s.font_bold_path)}" placeholder="auto"></label>
    <label class="f">Japanese/CJK font<input type="text" id="cjk_font_path" value="${esc(s.cjk_font_path)}" placeholder="auto"></label>
  </div>
  <div class="kv" style="margin-top:14px"><span class="muted">ffmpeg in use</span><span><code>${esc(st?.ffmpeg?.path)}</code> ${st?.ffmpeg?.version ? "✅ " + esc(st.ffmpeg.version.slice(0, 60)) : "❌ not found — install it or point to Jellyfin's ffmpeg"}</span>
    <span class="muted">Fonts</span><span>${Object.entries(st?.fonts || {}).map(([k, v]) => `${k}: <code>${esc(v || "not found")}</code>`).join(" ")}</span></div></div>
  <div class="card"><h2>🔒 Channel lock (kids mode)</h2>
    <label class="check"><input type="checkbox" id="lock_enabled" ${s.lock_enabled ? "checked" : ""}> Lock every channel that isn't marked as a Kids channel</label>
    <div class="form" style="margin-top:12px">
      <label class="f">${s.lock_has_code ? "Change lock code" : "Lock code"} (4–8 digits)<input type="password" inputmode="numeric" id="lock_new_code" autocomplete="new-password" placeholder="${s.lock_has_code ? "leave blank to keep" : "e.g. 4321"}"></label>
      <label class="f">Repeat the code<input type="password" inputmode="numeric" id="lock_new_code2" autocomplete="new-password"></label>
      <label class="f">One code entry unlocks a device for (minutes)<input type="number" id="lock_unlock_minutes" min="1" max="1440" value="${s.lock_unlock_minutes || 60}"></label>
      <label class="check wide"><input type="checkbox" id="lock_hide_in_jellyfin" ${s.lock_hide_in_jellyfin ? "checked" : ""}> Also hide locked channels from Jellyfin
        <span class="sub">(Jellyfin can't ask for a code; otherwise it shows every channel. Refresh Jellyfin's guide after changing this.)</span></label>
    </div>
    <p class="sub">Mark kids channels with the 🧸 switch in each channel's settings. With the lock on, the TV page and the phone remote ask for the code
      before playing or casting any other channel, and changing settings here needs the code too (unless you've set an admin password).</p></div>
  <div class="card"><h2>Chromecast</h2><div class="form">
    <label class="f">Chromecast IP addresses (optional)<input type="text" id="cast_hosts" value="${esc(s.cast_hosts || "")}" placeholder="192.168.1.50, 192.168.1.51"></label>
    <label class="f">Stream format for Chromecast<select id="cast_hls_format"><option value="fmp4">HLS fMP4 (recommended)</option>
      <option value="ts" ${s.cast_hls_format === "ts" ? "selected" : ""}>HLS MPEG-TS (legacy — older Cast players only)</option></select></label>
    <label class="check wide"><input type="checkbox" id="cast_watchdog" ${s.cast_watchdog !== false ? "checked" : ""}> Restart the stream automatically if a TV's picture freezes or gets stuck loading</label>
  </div><p class="sub">Chromecasts are found automatically on your network. Only add IP addresses if a TV doesn't show up (for example when it's on a different subnet, or Windows Firewall blocks discovery).</p>
  <div id="castdevs" class="sub">Looking for Chromecasts…</div></div>
  <div class="card"><h2>🌤 Weather maps</h2><div class="form">
    <label class="f">CARTO map key<input type="password" id="map_api_key" value="${esc(s.map_api_key || "")}" placeholder="needed for radar maps" autocomplete="off"></label>
  </div><p class="sub">The street maps under the weather channel's radar come from CARTO, which needs a free key
    (<a href="https://carto.com/basemaps/apikey/" target="_blank" rel="noopener">get one here</a>; leave “website” blank so it works from this server).
    Changes apply at the next radar refresh, within 10 minutes.</p></div>
  <div class="card"><h2>🧹 Maintenance</h2>
    <div class="row"><button class="btn danger" id="restart_server">↻ Restart server</button>
      <span class="sub" style="flex:1;min-width:260px">Stops every channel, stream and Chromecast connection and starts the server fresh, like closing and reopening it.
        Takes about 10 seconds. TVs that were casting come back on the same channel; browser viewers reconnect by themselves.</span></div></div>
  <div class="row"><span class="spacer"></span><button class="btn primary" id="save">Save settings</button></div></div>`;
  api("GET", "cast/devices").then((d) => {
    $("#castdevs").innerHTML = !d.available ? "❌ " + esc(d.error) : d.devices.length
      ? "Found: " + d.devices.map((x) => `<b>${esc(x.name)}</b> (${esc(x.model)}, ${esc(x.host)})`).join(", ") + `. TVs will load streams from <code>${esc(d.base_url)}</code>.`
      : `None found yet. TVs will load streams from <code>${esc(d.base_url)}</code> — that address must be reachable from the TV.`;
  }).catch(() => { });

  const ids = ["jellyfin_url", "jellyfin_api_key", "jellyfin_user_id", "public_url", "admin_password", "schedule_days", "epg_hours",
    "library_refresh_hours", "idle_timeout_seconds", "resolution", "framerate", "video_encoder", "encoder_preset", "video_bitrate_kbps",
    "audio_bitrate_kbps", "vaapi_device", "deinterlace", "tonemap_hdr", "media_access", "ffmpeg_path", "font_path", "font_bold_path", "cjk_font_path",
    "cast_hosts", "cast_hls_format", "cast_watchdog", "map_api_key", "lock_enabled", "lock_unlock_minutes", "lock_hide_in_jellyfin"];
  const nums = new Set(["lock_unlock_minutes", "schedule_days", "epg_hours", "library_refresh_hours", "idle_timeout_seconds", "framerate", "video_bitrate_kbps", "audio_bitrate_kbps"]);
  const collect = () => {
    const d = {};
    ids.forEach((k) => { const e = $("#" + k); d[k] = e.type === "checkbox" ? e.checked : nums.has(k) ? +e.value : e.value.trim(); });
    d.path_mappings = $("#path_mappings").value.split("\n").map((l) => l.split("=>").map((x) => x.trim())).filter((p) => p.length === 2 && p[0])
      .map(([from, to]) => ({ from, to }));
    return d;
  };
  const test = async () => {
    $("#testres").textContent = "Testing…";
    try {
      const r = await api("POST", "settings/test", collect());
      $("#testres").innerHTML = `✅ Connected to <b>${esc(r.server)}</b> (Jellyfin ${esc(r.version)}${r.os ? ", " + esc(r.os) : ""})`;
      const sel = $("#jellyfin_user_id"), cur = sel.value;
      sel.innerHTML = '<option value="">First administrator</option>' + r.users.map((u) => `<option value="${u.id}" ${u.id === cur ? "selected" : ""}>${esc(u.name)}${u.admin ? " (admin)" : ""}</option>`).join("");
    } catch (e) { $("#testres").textContent = "❌ " + e.message; }
  };
  $("#test").onclick = test;
  $("#restart_server").onclick = () => restartServer();
  $("#save").onclick = async () => {
    const d = collect();
    const c1 = $("#lock_new_code").value.trim(), c2 = $("#lock_new_code2").value.trim();
    if (c1 || c2) {
      if (c1 !== c2) return toast("The two lock codes don't match", true);
      if (!/^[0-9]{4,8}$/.test(c1)) return toast("The lock code must be 4 to 8 digits", true);
      d.lock_new_code = c1;
    }
    try {
      await api("POST", "settings", d); toast("Settings saved");
      $("#lock_new_code").value = $("#lock_new_code2").value = "";
    } catch (e) { toast(e.message, true); }
  };
  if (st?.configured) test();
}

async function restartServer() {
  if (!confirm("Restart the server now? Everyone watching sees a few seconds of interruption.")) return;
  let before = null;
  try { before = (await api("GET", "status")).started; } catch { }
  try { await api("POST", "server/restart"); } catch (e) { return toast(e.message, true); }
  const ov = document.createElement("div");
  ov.style.cssText = "position:fixed;inset:0;background:#000c;display:grid;place-items:center;z-index:80;color:#fff;font-size:20px;text-align:center";
  ov.innerHTML = '<div><div style="font-size:48px">↻</div><div id="rs_msg">Restarting the server…</div><div class="sub" id="rs_sub" style="margin-top:8px"></div></div>';
  document.body.appendChild(ov);
  const t0 = Date.now();
  await new Promise((r) => setTimeout(r, 1500));
  while (Date.now() - t0 < 90000) {
    try {
      const st = await (await fetch("/api/status", { headers: { "X-Unlock": unlockTok() }, cache: "no-store" })).json();
      if (st.started && st.started !== before) {
        $("#rs_msg").textContent = "Back on the air ✓";
        await new Promise((r) => setTimeout(r, 800));
        location.reload(); return;
      }
    } catch { }
    $("#rs_sub").textContent = `${Math.round((Date.now() - t0) / 1000)} s`;
    await new Promise((r) => setTimeout(r, 1000));
  }
  $("#rs_msg").textContent = "The server hasn’t come back yet — check its window or broadcast.log.";
}

// --------------------------------------------------------------------------- connect
async function showConnect() {
  const st = await loadStatus();
  const base = st?.base_url || location.origin;
  const c = (label, url) => `<div class="f" style="margin:8px 0"><span class="sub">${label}</span><div class="copy"><code>${esc(url)}</code><button class="btn small" data-copy="${esc(url)}">Copy</button></div></div>`;
  view.innerHTML = `<h1>Connect to Jellyfin</h1><div class="stack">
  <div class="card"><h2>1. Add the tuner</h2><ol class="steps">
    <li>In Jellyfin open <b>Dashboard → Live TV</b>.</li>
    <li>Under <b>Tuner Devices</b> click <b>+</b>, choose <b>M3U Tuner</b> and paste:${c("M3U playlist", base + "/iptv/channels.m3u")}</li>
    <li>Leave “Allow hardware transcoding” off if you like — the streams are already H.264/AAC. Save.</li></ol></div>
  <div class="card"><h2>2. Add the guide data</h2><ol class="steps">
    <li>Under <b>TV Guide Data Providers</b> click <b>+</b>, choose <b>XMLTV</b> and paste:${c("XMLTV guide", base + "/iptv/xmltv.xml")}</li>
    <li>Optional: in the XMLTV settings, set <b>Movie categories</b> to <code>Movie</code> so films show up as movies.</li>
    <li>Save, then click <b>Refresh Guide Data</b> (or run the “Refresh Guide” scheduled task).</li></ol>
    <p class="sub">Channels and logos appear in Jellyfin's <b>Live TV</b> section in every app — TV, phone, browser. If Jellyfin runs on another machine, make sure this address is reachable from it (set it under Settings if the auto-detected one is wrong).</p></div>
  <div class="card"><h2>📺 On the TV itself (Google TV / Android TV app)</h2>
    <div class="row" style="align-items:flex-start;gap:28px">
      <div class="stack" style="align-items:center;gap:6px"><div class="qr" data-qr="${esc(base + "/app")}"></div><b>TV app</b></div>
      <div style="flex:1;min-width:260px"><p style="margin-top:0">Install the <b>${esc(BRAND.short)}</b> app on a Google TV Streamer, Chromecast with Google TV or any
        Android TV and watch with the <b>TV remote</b>: ▲▼ change channel, OK opens the guide, ◀ last channel, Back closes.</p>
        <p>Install instructions and the download: ${c("TV app page", base + "/app")}</p></div></div></div>
  <div class="card"><h2>On your phone</h2>
    <div class="row" style="align-items:flex-start;gap:28px">
      <div class="stack" style="align-items:center;gap:6px"><div class="qr" data-qr="${esc(base + "/remote")}"></div><b>📱 Remote</b>
        <span class="sub" style="max-width:220px;text-align:center">Control a Chromecast: channel and volume rockers, number pad, guide.</span></div>
      <div class="stack" style="align-items:center;gap:6px"><div class="qr" data-qr="${esc(base + "/tv")}"></div><b>▶ Watch</b>
        <span class="sub" style="max-width:220px;text-align:center">Watch on the phone, or cast from it.</span></div>
      <p class="sub" style="flex:1;min-width:220px">Scan with the phone's camera. To keep the remote handy, use the browser's <b>Add to Home screen</b>;
        it then opens full-screen like an app. Your phone must be on the same Wi-Fi as this server.</p></div></div>
  <div class="card"><h2>Other ways to watch</h2>
    ${c("Watch in a browser (channel surfing + guide)", base + "/tv")}
    ${c("Phone remote for casting", base + "/remote")}
    ${c("HDHomeRun emulation (Plex, Emby, Channels DVR)", base)}
    <p class="sub">Any IPTV player (VLC, TiviMate, Kodi) can also open the M3U playlist directly.</p></div></div>`;
  $$("[data-copy]").forEach((b) => (b.onclick = () => copy(b.dataset.copy)));
  $$("[data-qr]").forEach((el) => {
    try { const q = qrcode(0, "M"); q.addData(el.dataset.qr); q.make();
      el.innerHTML = q.createSvgTag({ cellSize: 5, margin: 3, scalable: true });
      el.style.cssText = "width:180px;height:180px;background:#fff;border-radius:10px;padding:4px"; } catch (e) { el.textContent = el.dataset.qr; }
  });
}

route();
loadStatus();
