/* Browser TV + phone remote.
   /tv     : watch channels here (mpegts.js), or cast them and use this page as the remote.
   /remote : remote control only - never plays video on the phone, just drives a Chromecast. */
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const REMOTE_ONLY = document.body.classList.contains("mode-remote");
// running inside the Barnes TV app on a Google TV / Android TV box: driven by the TV remote, no mouse or touch
const APP = new URLSearchParams(location.search).has("app");
if (APP) document.body.classList.add("app");
const video = $("#v");
let castDev = null;
let channels = [], idx = 0, player = null, on = false, digits = "", digitTimer, osdTimer, bannerTimer, uiTimer, retryTimer, gsel = 0;

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { } },
};
// ---------------------------------------------------------------- channel lock (enforced by the server)
let lockInfo = { enabled: false };
function unlockTok() {
  try { const u = JSON.parse(store.get("jfb-unlock") || "null"); return u && u.until * 1000 > Date.now() ? u.token : ""; } catch { return ""; }
}
const authHeaders = (h = {}) => { const t = unlockTok(); if (t) h["X-Unlock"] = t; return h; };
const isBlocked = (ch) => ch && ch.locked && !unlockTok();
async function refreshLock() {
  try { lockInfo = await (await fetch("/api/lock/status", { headers: authHeaders() })).json(); } catch { }
  const show = lockInfo.enabled && !!unlockTok();
  $("#grelock").style.display = show ? "" : "none";
  $("#rrelock").style.display = show ? "" : "none";
}
let pinCode = "", pinFor = null;
function showLock(ch) {
  pinFor = ch; pinCode = "";
  stopLocal();
  $("#locktitle").textContent = `${ch.number} · ${ch.name} is locked`;
  $("#locklogo").src = ch.logo_url;
  $("#pin").textContent = ""; $("#pinmsg").textContent = "";
  $("#lock").classList.add("on");
  $("#banner").classList.remove("on");
  if (APP) { pinFocus = 4; pinFocusDraw(); }
}
function hideLock() { $("#lock").classList.remove("on"); pinFor = null; pinCode = ""; }
function pinKey(k) {
  haptic();
  if (k === "back") pinCode = pinCode.slice(0, -1);
  else if (k === "go") return submitPin();
  else if (pinCode.length < 8) pinCode += k;
  $("#pin").textContent = "•".repeat(pinCode.length);
  $("#pinmsg").textContent = "";
}
async function submitPin() {
  if (!pinCode) return;
  try {
    const r = await fetch("/api/lock/unlock", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: pinCode }) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || "Wrong code");
    store.set("jfb-unlock", JSON.stringify({ token: d.token, until: d.until }));
    const ch = pinFor; hideLock(); refreshLock();
    showOSD("🔓");
    const i = ch ? channels.findIndex((c) => c.id === ch.id) : -1;
    tune(i >= 0 ? i : idx);
  } catch (e) {
    pinCode = ""; $("#pin").textContent = ""; $("#pinmsg").textContent = e.message;
    $("#lock .box").classList.remove("shake"); void $("#lock .box").offsetWidth; $("#lock .box").classList.add("shake");
  }
}
$$("#lock [data-p]").forEach((b) => (b.onclick = () => pinKey(b.dataset.p)));
$("#lockkids").onclick = () => {
  const n = channels.length;
  for (let k = 1; k <= n; k++) { const j = (idx + k) % n; if (!channels[j].locked) { hideLock(); return tune(j); } }
  $("#pinmsg").textContent = "No kids channels are set up yet.";
};
async function relock() {
  try { await fetch("/api/lock/lock", { method: "POST", headers: authHeaders() }); } catch { }
  store.set("jfb-unlock", "");
  await refreshLock();
  showOSD("🔒");
  if (isBlocked(channels[idx])) tune(idx);
}
$("#grelock").onclick = () => { toggleGuide(false); relock(); };
$("#rrelock").onclick = (e) => { e.preventDefault(); relock(); };
setInterval(() => {   // an unlock ran out while watching a locked channel
  if (on && !$("#lock").classList.contains("on") && isBlocked(channels[idx])) { refreshLock(); tune(idx); }
}, 20000);

const haptic = () => { try { navigator.vibrate && navigator.vibrate(8); } catch { } };

let channelsAt = 0;
async function loadChannels() {
  const r = await fetch("/api/channels");
  const list = (await r.json()).filter((c) => c.enabled);
  list.sort((a, b) => a.number - b.number);
  const keep = channels[idx] && channels[idx].id;      // read after the wait: the viewer may have changed channel
  channels = list;
  channelsAt = Date.now();
  if (keep) { const i = channels.findIndex((c) => c.id === keep); if (i >= 0) idx = i; }   // stay on the same channel
}
// what's-on data is old: fetched a while ago, or the show it says is on has already ended
function nowInfoStale(ch) {
  return Date.now() - channelsAt > 20000 || !!(ch && ch.now && ch.now.end * 1000 <= Date.now());
}

// notes for the server log (broadcast.log), so odd behaviour on a TV can be traced afterwards
function clog(detail, info) {
  try {
    fetch("/api/client-log", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app: APP, type: "note", channel: channels[idx] ? channels[idx].number : "?", detail, info: info || "" }) });
  } catch { }
}
// ---------------------------------------------------------------- static noise between channels
const nc = $("#noise"), nctx = nc.getContext("2d");
let noiseOn = false;
function noise(show) {
  noiseOn = show; nc.classList.toggle("on", show);
  if (show) requestAnimationFrame(drawNoise);
}
function drawNoise() {
  if (!noiseOn) return;
  const img = nctx.createImageData(nc.width, nc.height), d = img.data;
  for (let i = 0; i < d.length; i += 4) { const v = Math.random() * 255 | 0; d[i] = d[i + 1] = d[i + 2] = v; d[i + 3] = 255; }
  nctx.putImageData(img, 0, 0);
  requestAnimationFrame(drawNoise);
}

// ---------------------------------------------------------------- tuning
let prevIdx = null;
function tune(i) {
  if (!channels.length) return;
  const next = (i + channels.length) % channels.length;
  if (next !== idx) prevIdx = idx;
  idx = next;
  const ch = channels[idx];
  if (!REMOTE_ONLY) location.replace("#" + encodeURIComponent(ch.number));
  store.set("jfb-last", ch.number);
  showOSD(String(ch.number));
  armSleep();
  if (isBlocked(ch)) return showLock(ch);
  hideLock();
  if (castDev) return castTune(ch);
  if (REMOTE_ONLY) return openCastPicker();
  showBanner();
  noise(true);
  $("#msg").style.display = "none";
  clearTimeout(retryTimer);
  if (player) { try { player.destroy(); } catch { } player = null; }
  if (!window.mpegts || !mpegts.getFeatureList().mseLivePlayback) {
    noise(false);
    $("#msg").textContent = "This browser can't play live streams. Tap Cast to watch on a TV (this page becomes the remote), or use the Jellyfin app's Live TV.";
    $("#msg").style.display = "block";
    return;
  }
  const tok = unlockTok();
  player = mpegts.createPlayer({ type: "mpegts", isLive: true, url: `${location.origin}/stream/${ch.id}.ts${tok ? "?unlock=" + encodeURIComponent(tok) : ""}` },
    { enableWorker: true, lazyLoad: false, liveBufferLatencyChasing: true, liveBufferLatencyMaxLatency: 16, liveBufferLatencyMinRemain: 3, enableStashBuffer: false });
  player.attachMediaElement(video);
  player.on(mpegts.Events.ERROR, (type, detail, info) => {
    try {
      fetch("/api/client-log", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel: ch.number, type, detail, info: info && (info.msg || JSON.stringify(info)) }) });
    } catch { }
    noise(true);
    retryTimer = setTimeout(() => { if (channels[idx] === ch && !castDev) tune(idx); }, 2500);
  });
  player.load();
  const p = player.play();
  if (p && p.catch) p.catch(() => { });
}
video.addEventListener("playing", () => { noise(false); watchPicture(); });
// Android TV's WebView sometimes plays the sound but leaves the picture black until something redraws the screen
// (opening and closing the guide "fixed" it). Check that frames really reach the screen; if not, force a redraw,
// and if that doesn't help, tune in again.
let picWatch = null, picTry = 0, picTuneId = null;
function frameCount() {
  try { const q = video.getVideoPlaybackQuality && video.getVideoPlaybackQuality(); if (q) return q.totalVideoFrames; } catch { }
  return video.webkitDecodedFrameCount ?? null;
}
function repaint() {
  video.style.visibility = "hidden"; void video.offsetHeight;
  requestAnimationFrame(() => { video.style.visibility = ""; video.style.transform = video.style.transform ? "" : "translateZ(0)"; });
}
function watchPicture() {
  clearTimeout(picWatch);
  const ch = channels[idx];
  if (!ch) return;
  if (picTuneId !== ch.id) { picTuneId = ch.id; picTry = 0; }
  if (APP) repaint();                       // cheap insurance on the TV app: one redraw as the picture starts
  const t0 = video.currentTime, f0 = frameCount();
  picWatch = setTimeout(() => {
    if (channels[idx] !== ch || dark || video.paused) return;
    const moved = video.currentTime - t0, f1 = frameCount();
    const noPicture = video.videoWidth === 0 || (f1 !== null && f0 !== null && f1 - f0 < 5 && moved > 2);
    if (!noPicture) return;
    picTry++;
    clog("no picture", `size ${video.videoWidth}x${video.videoHeight}, frames ${f0}->${f1}, ${moved.toFixed(1)}s played, try ${picTry}`);
    if (picTry === 1) { repaint(); watchPicture(); }
    else if (picTry === 2) tune(idx);
  }, 4000);
}
video.addEventListener("waiting", () => { if (video.currentTime < 1) noise(true); });
function stopLocal() {
  if (player) { try { player.destroy(); } catch { } player = null; }
  noise(false);
}

// ---------------------------------------------------------------- volume (this device, or the TV when casting)
let localVol = parseFloat(store.get("jfb-vol") ?? "1");
if (isNaN(localVol)) localVol = 1;
video.volume = localVol;
video.muted = store.get("jfb-muted") === "1";
const castVolume = { level: 0.5, muted: false };
let volTimer;
function showVol() {
  const level = castDev ? castVolume.level : localVol, muted = castDev ? castVolume.muted : video.muted;
  const pct = Math.round(level * 100);
  $("#volbar").style.width = (muted ? 0 : pct) + "%";
  $("#volnum").textContent = muted ? "MUTE" : pct;
  $("#volicon").textContent = muted || pct === 0 ? "🔇" : pct < 40 ? "🔈" : pct < 75 ? "🔉" : "🔊";
  $("#vol").classList.add("on");
  clearTimeout(volTimer);
  volTimer = setTimeout(() => $("#vol").classList.remove("on"), 1800);
  updateMuteIcons();
  if (castDev) $("#castvol").value = pct; else $("#localvol").value = pct;
}
function updateMuteIcons() {
  $("#muteicon").textContent = video.muted ? "🔇" : "🔊";
  $("#castmute").classList.toggle("on", castVolume.muted);
}
function setLocalVolume(v) {
  localVol = Math.round(Math.min(1, Math.max(0, v)) * 100) / 100;
  video.volume = localVol;
  if (video.muted && localVol > 0) video.muted = false;
  store.set("jfb-vol", String(localVol)); store.set("jfb-muted", video.muted ? "1" : "");
  showVol();
}
$("#localvol").value = Math.round(localVol * 100);
$("#localvol").oninput = (e) => setLocalVolume(e.target.value / 100);
document.addEventListener("wheel", (e) => {
  if ($("#guide").classList.contains("on") || $("#castpick").classList.contains("on") || castDev) return;
  action(e.deltaY < 0 ? "volup" : "voldown");
}, { passive: true });

// ---------------------------------------------------------------- casting (the server talks to the Chromecast)
let castPoll = null, castVolTimer = null, lastChannelRefresh = 0;
async function capi(act, body) {
  const r = await fetch("/api/cast/" + act, body ? { method: "POST", headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(body) } : { headers: authHeaders() });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { const err = new Error(d.error || r.statusText); err.locked = !!d.locked; throw err; }
  return d;
}
function setStatus(cls, text) {
  $("#caststatus").className = cls; $("#caststatus").textContent = text;
  $("#castdot").className = "dot " + (cls === "ok" ? "ok" : cls === "error" ? "err" : "wait");
}
async function pollCast() {
  if (!castDev) return;
  try {
    if (Date.now() - lastChannelRefresh > 30000) { lastChannelRefresh = Date.now(); await loadChannels(); renderRemote(); }
    const d = await capi("devices");
    const dev = (d.devices || []).find((x) => x.id === castDev.id);
    if (!dev) return setStatus("error", "The TV is no longer on the network.");
    if (typeof dev.volume === "number" && !castVolTimer) {
      castVolume.level = dev.volume; castVolume.muted = dev.muted;
      $("#castvol").value = Math.round(dev.volume * 100); updateMuteIcons();
    }
    if (dev.channel && channels[idx] && dev.channel !== channels[idx].id && !$("#lock").classList.contains("on")
        && Date.now() - lastTuneAt > 8000) {   // changed elsewhere (not by a switch from here that's still on its way)
      const i = channels.findIndex((c) => c.id === dev.channel);
      if (i >= 0) { idx = i; renderRemote(); }
    }
    if (dev.status === "playing") setStatus("ok", "● Playing on the TV");
    else setStatus(dev.status === "error" || dev.status === "unreachable" ? "error" : "", dev.message || "");
  } catch { }
}
function castVolumeSet(body) {
  capi("volume", Object.assign({ device: castDev.id }, body)).then((r) => {
    castVolume.level = r.volume ?? castVolume.level; castVolume.muted = !!r.muted; showVol();
  }).catch((e) => setStatus("error", e.message));
}
$("#castvol").oninput = (e) => {
  castVolume.level = e.target.value / 100; showVol();
  clearTimeout(castVolTimer);
  castVolTimer = setTimeout(() => { castVolTimer = null; castVolumeSet({ level: castVolume.level }); }, 150);
};
function renderRemote() {
  const ch = channels[idx];
  if (!castDev || !ch) return;
  document.body.classList.remove("ui");
  $("#remote").classList.add("on");
  if (!castPoll) castPoll = setInterval(pollCast, 3000);
  $("#castname").textContent = castDev.name;
  $("#castlogo").src = ch.logo_url;
  $("#castnow").textContent = `${ch.number} · ${ch.name}`;
  const n = ch.now, nx = ch.next, now = Date.now() / 1000;
  $("#casttitle").textContent = ch.type === "guide" ? "Program Guide" : n ? n.title : "";
  $("#castsub").textContent = n && n.subtitle ? n.subtitle : "";
  $("#castprog").style.width = n ? Math.min(100, Math.max(0, ((now - n.start) / (n.end - n.start)) * 100)) + "%" : "0%";
  $("#casttimes").textContent = n ? `${fmt(n.start)} – ${fmt(n.end)}` : "";
  $("#castnext").textContent = nx ? `Next: ${nx.title}` : "";
  $("#stopbtn").textContent = REMOTE_ONLY ? "Turn off TV playback" : "Stop casting · watch here";
}
let castTuneTimer = null, lastTuneAt = 0;
function castTune(ch) {
  // flipping through channels: the remote follows every press, the TV only gets the one you stop on
  stopLocal();
  lastTuneAt = Date.now();
  setStatus("", "Changing channel on the TV…");
  renderRemote();
  clearTimeout(castTuneTimer);
  castTuneTimer = setTimeout(async () => {
    lastTuneAt = Date.now();
    try { await capi("play", { device: castDev.id, channel: ch.id }); }
    catch (e) {
      if (e.locked) { store.set("jfb-unlock", ""); refreshLock(); return showLock(ch); }
      setStatus("error", "Couldn't cast: " + e.message);
    }
  }, 450);
}
async function castReload() {
  if (!castDev) return;
  setStatus("", "Restarting the stream on the TV…");
  lastTuneAt = Date.now();
  try { await capi("reload", { device: castDev.id }); }
  catch (e) {   // the server lost track of what's on (e.g. it restarted): just tune the channel again
    if (channels[idx]) castTune(channels[idx]); else setStatus("error", e.message);
  }
}
function attach(dev, channelId) {
  castDev = { id: dev.id, name: dev.name };
  store.set("jfb-cast", JSON.stringify(castDev));
  stopLocal();
  const i = channels.findIndex((c) => c.id === channelId);
  if (i >= 0) idx = i;
  setStatus("", "Connected");
  renderRemote(); pollCast();
}
async function openCastPicker() {
  $("#castpick").classList.add("on");
  $("#castlist").innerHTML = "";
  $("#casthint").textContent = "Looking for Chromecasts…";
  $("#castclose").textContent = REMOTE_ONLY && !castDev ? "Search again" : "Close";
  let d;
  for (let tries = 0; tries < 3; tries++) {
    try { d = await capi("devices"); } catch (e) { $("#casthint").textContent = e.message; return; }
    if (!d.available || d.devices.length) break;
    await new Promise((r) => setTimeout(r, 1500));
  }
  if (!d.available) { $("#casthint").textContent = d.error || "Casting isn't available on this server."; return; }
  const chName = (id) => { const c = channels.find((x) => x.id === id); return c ? `${c.number} ${c.name}` : "a channel"; };
  $("#casthint").textContent = d.devices.length ? (REMOTE_ONLY ? "Pick the TV to control." : "Pick a TV. This page becomes the remote.") :
    "No Chromecasts found. Make sure the TV is on and on the same network, or add its IP address under Settings → Chromecast in the admin page.";
  $("#castlist").innerHTML = (castDev && !REMOTE_ONLY ? `<button class="dev" data-stop="1">📱 Watch on this device<small>Stops casting to ${esc(castDev.name)}</small></button>` : "") +
    d.devices.map((x) => `<button class="dev ${castDev && castDev.id === x.id ? "on" : ""}" data-id="${esc(x.id)}" data-name="${esc(x.name)}" data-ch="${esc(x.channel || "")}">📺 ${esc(x.name)}
      <small>${x.channel ? `Showing ${esc(chName(x.channel))} — tap to control it` : `${esc(x.model || "")} · tap to start ${esc(channels[idx] ? channels[idx].number + " " + channels[idx].name : "watching")}`}</small></button>`).join("");
  $$("#castlist .dev").forEach((b) => (b.onclick = async () => {
    haptic();
    $("#castpick").classList.remove("on");
    if (b.dataset.stop) return stopCasting();
    if (b.dataset.ch) return attach({ id: b.dataset.id, name: b.dataset.name }, b.dataset.ch);
    castDev = { id: b.dataset.id, name: b.dataset.name };
    store.set("jfb-cast", JSON.stringify(castDev));
    tune(idx);
  }));
}
$("#castclose").onclick = () => {
  if (REMOTE_ONLY && !castDev) return openCastPicker();
  $("#castpick").classList.remove("on");
};
async function stopCasting() {
  const dev = castDev; castDev = null; store.set("jfb-cast", "");
  $("#remote").classList.remove("on");
  clearInterval(castPoll); castPoll = null;
  if (dev) { try { await capi("stop", { device: dev.id }); } catch { } }
  if (REMOTE_ONLY) openCastPicker(); else tune(idx);
}

// ---------------------------------------------------------------- number pad (remote) and number keys
function numberKey(d) {
  digits = (digits + d).slice(-4);
  showOSD(digits + "-");
  $("#numdisp").textContent = digits;
  clearTimeout(digitTimer);
  digitTimer = setTimeout(goDigits, 1600);
}
function goDigits() {
  clearTimeout(digitTimer);
  if (!digits) return;
  const i = channels.findIndex((c) => String(c.number) === digits || Math.floor(c.number) === +digits);
  digits = ""; $("#numdisp").textContent = "";
  if (i >= 0) { tune(i); $("#numpad").classList.remove("on"); $("#numbtn").classList.remove("on"); }
  else { showOSD("--"); $("#numdisp").textContent = "no such channel"; setTimeout(() => ($("#numdisp").textContent = ""), 1200); }
}
$$("#numpad .keys button").forEach((b) => (b.onclick = () => {
  haptic();
  const k = b.dataset.k;
  if (k === "back") { digits = digits.slice(0, -1); $("#numdisp").textContent = digits; clearTimeout(digitTimer); }
  else if (k === "go") goDigits();
  else numberKey(k);
}));

// ---------------------------------------------------------------- OSD + banner
function showOSD(text) {
  $("#osd").textContent = text;
  $("#osd").classList.add("on");
  clearTimeout(osdTimer);
  osdTimer = setTimeout(() => $("#osd").classList.remove("on"), 2500);
}
async function showBanner(refresh) {
  if (castDev) {
    if (refresh || nowInfoStale(channels[idx])) { try { await loadChannels(); } catch { } }
    return renderRemote();
  }
  const ch = channels[idx]; if (!ch) return;
  drawBanner(ch);
  if (refresh || nowInfoStale(ch)) {    // show what we have straight away, then correct it with fresh listings
    try { await loadChannels(); } catch { return; }
    const fresh = channels[idx];
    if (fresh && fresh.id === ch.id && $("#banner").classList.contains("on")) drawBanner(fresh, true);
  }
}
function drawBanner(ch, keepTimer) {
  const n = ch.now, nx = ch.next, now = Date.now() / 1000;
  const pct = n ? Math.min(100, Math.max(0, ((now - n.start) / (n.end - n.start)) * 100)) : 0;
  $("#banner").innerHTML = `<div class="num">${esc(ch.number)}</div><img src="${ch.logo_url}" alt="">
    <div style="flex:1;min-width:0">
      <div class="s">${esc(ch.name)}</div>
      <div class="t">${esc(ch.type === "guide" ? "Program Guide" : n ? n.title : "Off the air")}</div>
      ${n && n.subtitle ? `<div class="s">${esc(n.subtitle)}</div>` : ""}
      ${n ? `<div class="bar"><div style="width:${pct}%"></div></div><div class="nx">${fmt(n.start)} – ${fmt(n.end)}${nx ? ` · Next: <b>${esc(nx.title)}</b> at ${fmt(nx.start)}` : ""}</div>` : ""}
    </div><div class="clock">${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</div>`;
  $("#banner").classList.add("on");
  if (keepTimer) return;
  clearTimeout(bannerTimer);
  bannerTimer = setTimeout(() => $("#banner").classList.remove("on"), 5000);
}

// ---------------------------------------------------------------- guide overlay
async function toggleGuide(force) {
  const g = $("#guide"), show = force ?? !g.classList.contains("on");
  g.classList.toggle("on", show);
  if (!show) return;
  gsel = idx;                // before the refresh: an OK pressed meanwhile must not land on an old selection
  await loadChannels();
  gsel = idx;
  renderGuide();
}
// extra rows at the bottom of the guide
const guideExtras = () => [!castDev && !REMOTE_ONLY ? "screen" : null, APP && window.BarnesApp ? "server" : null].filter(Boolean);
const guideRows = () => channels.length + guideExtras().length;
function guideExtra(key) {
  if (key === "server") return window.BarnesApp && BarnesApp.changeServer();
  if (key === "screen") { toggleGuide(false); screenOff(true, "guide row"); }
}
function renderGuide() {
  $("#gclock").textContent = new Date().toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
  $("#glist").innerHTML = (APP && window.BarnesApp ? "" : "") + channels.map((c, i) => `<div class="gi ${i === gsel ? "sel" : ""} ${i === idx ? "cur" : ""}" data-i="${i}">
    <div class="n">${esc(c.number)}</div><img src="${c.logo_url}" alt="">
    <div><b>${isBlocked(c) ? "🔒 " : ""}${esc(c.type === "guide" ? "Program Guide" : c.now ? c.now.title : "—")}</b><small>${esc(c.name)}${c.now ? " · until " + fmt(c.now.end) : ""}</small></div>
    <div>${c.next ? `<small>Next: </small><b>${esc(c.next.title)}</b><small> ${fmt(c.next.start)}</small>` : ""}</div></div>`).join("") +
    guideExtras().map((key, k) => `<div class="gi ${gsel === channels.length + k ? "sel" : ""}" data-x="${key}">` + (key === "screen"
      ? `<div class="n">🌙</div><div></div><div><b>Turn the screen off</b><small>The picture goes black, the sound keeps playing. Any button brings it back.</small></div><div></div></div>`
      : `<div class="n">⚙</div><div></div><div><b>Switch server</b><small>Connect this TV to a different ${esc((window.BRAND && window.BRAND.short) || "Barnes TV")} server</small></div><div></div></div>`)).join("");
  $$(".gi").forEach((el) => (el.onclick = () => {
    haptic();
    if (el.dataset.x) return guideExtra(el.dataset.x);
    toggleGuide(false); tune(+el.dataset.i);
  }));
  const sel = $(".gi.sel"); if (sel) sel.scrollIntoView({ block: "nearest" });
}
$("#gclose").onclick = () => toggleGuide(false);

// ---------------------------------------------------------------- input
function action(a) {
  if (a === "up") tune(idx + 1);
  else if (a === "down") tune(idx - 1);
  else if (a === "guide") toggleGuide();
  else if (a === "info") showBanner(true);
  else if (a === "cast") openCastPicker();
  else if (a === "stopcast") stopCasting();
  else if (a === "reload") castReload();
  else if (a === "numpad") { const o = $("#numpad").classList.toggle("on"); $("#numbtn").classList.toggle("on", o); if (o) $("#numpad").scrollIntoView({ behavior: "smooth", block: "nearest" }); }
  else if (castDev && (a === "mute" || a === "volup" || a === "voldown")) {
    if (a === "mute") castVolumeSet({ mute: !castVolume.muted });
    else castVolumeSet({ level: Math.min(1, Math.max(0, castVolume.level + (a === "volup" ? 0.05 : -0.05))) });
  }
  else if (a === "volup" || a === "voldown") setLocalVolume(localVol + (a === "volup" ? 0.05 : -0.05));
  else if (a === "mute") { video.muted = !video.muted; store.set("jfb-muted", video.muted ? "1" : ""); showVol(); }
  else if (a === "screen") screenOff(true, "screen-off button");
  else if (a === "full") { document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen?.(); }
}
// ---- TV remote (the Android TV app): D-pad ▲▼ = channel, OK = guide, ◀ = last channel, ▶ = info, Back = close
let pinFocus = 4;
function pinFocusDraw() {
  const keys = [...$$("#lock .keys button"), $("#lockkids")];
  keys.forEach((k, i) => k.classList.toggle("focus", i === pinFocus));
}
function appKey(e) {
  const k = e.key;
  if ($("#lock").classList.contains("on")) {
    const keys = [...$$("#lock .keys button"), $("#lockkids")];
    if (k === "ArrowLeft" || k === "ArrowRight") {
      if (pinFocus < 12) pinFocus = Math.floor(pinFocus / 3) * 3 + ((pinFocus % 3) + (k === "ArrowRight" ? 1 : 2)) % 3;
    } else if (k === "ArrowUp") pinFocus = pinFocus === 12 ? 10 : pinFocus >= 3 ? pinFocus - 3 : pinFocus;
    else if (k === "ArrowDown") pinFocus = pinFocus >= 9 ? 12 : pinFocus + 3;
    else if (k === "Enter") { keys[pinFocus].click(); return true; }
    else return false;
    pinFocusDraw(); return true;
  }
  if ($("#guide").classList.contains("on") || $("#castpick").classList.contains("on")) return k === "ArrowLeft" || k === "ArrowRight";
  if (k === "Enter") { action("guide"); return true; }
  if (k === "ArrowLeft") { if (prevIdx !== null) tune(prevIdx); return true; }
  if (k === "ArrowRight") { showBanner(true); return true; }
  return false;
}
window.tvKey = (k) => {        // keys the app forwards from the remote (CH+/CH-, Guide, Info, Last)
  if (!on) return powerOn();
  if (dark) return screenOff(false);
  if (k === "chup") action("up");
  else if (k === "chdown") action("down");
  else if (k === "guide") action("guide");
  else if (k === "info") showBanner(true);
  else if (k === "last" && prevIdx !== null) tune(prevIdx);
};
window.tvBack = () => {        // true = handled; false = let the app close
  if (dark) { screenOff(false); return true; }
  if ($("#castpick").classList.contains("on")) { $("#castpick").classList.remove("on"); return true; }
  if ($("#guide").classList.contains("on")) { toggleGuide(false); return true; }
  if ($("#lock").classList.contains("on")) { $("#lockkids").click(); return true; }
  if ($("#banner").classList.contains("on")) { $("#banner").classList.remove("on"); return true; }
  return false;
};
window.tvSuspend = () => { stopLocal(); };
window.tvResume = () => { if (on && !castDev) tune(idx); };

document.addEventListener("keydown", (e) => {
  if (!on) return powerOn();
  if (dark) {     // volume still works in the dark; anything else just brings the picture back
    const vol = { "+": "volup", "=": "volup", "]": "volup", "-": "voldown", "_": "voldown", "[": "voldown", m: "mute", M: "mute",
      AudioVolumeUp: "volup", AudioVolumeDown: "voldown", AudioVolumeMute: "mute" }[e.key];
    e.preventDefault();
    if (vol) return action(vol);
    return screenOff(false);
  }
  if (APP && appKey(e)) { e.preventDefault(); return; }
  if ($("#lock").classList.contains("on")) {
    if (/^[0-9]$/.test(e.key)) return pinKey(e.key);
    if (e.key === "Backspace") return pinKey("back");
    if (e.key === "Enter") return pinKey("go");
    if (!["ArrowUp", "ArrowDown", "PageUp", "PageDown", "g", "G", "c", "C"].includes(e.key)) return;
  }
  const g = $("#guide").classList.contains("on");
  if (g && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
    gsel = (gsel + (e.key === "ArrowUp" ? -1 : 1) + guideRows()) % guideRows(); renderGuide(); e.preventDefault(); return;
  }
  if (g && e.key === "Enter") {
    if (gsel >= channels.length) return guideExtra(guideExtras()[gsel - channels.length]);
    toggleGuide(false); tune(gsel); return;
  }
  if (e.key === "Escape") { $("#castpick").classList.remove("on"); return toggleGuide(false); }
  const map = { ArrowUp: "up", PageUp: "up", ArrowDown: "down", PageDown: "down", g: "guide", G: "guide",
    "+": "volup", "=": "volup", "]": "volup", "-": "voldown", "_": "voldown", "[": "voldown",
    AudioVolumeUp: "volup", AudioVolumeDown: "voldown", AudioVolumeMute: "mute",
    i: "info", I: "info", m: "mute", M: "mute", f: "full", F: "full", c: "cast", C: "cast", Enter: "info" };
  if (/^[0-9]$/.test(e.key)) return numberKey(e.key);
  if (map[e.key]) { e.preventDefault(); action(map[e.key]); }
});
$$("#controls button, #remote button[data-a]").forEach((b) => (b.onclick = (e) => {
  e.stopPropagation(); haptic(); action(b.dataset.a); if (b.closest("#controls")) showUI();
}));
if (!document.fullscreenEnabled) $("#fullbtn").style.display = "none";    // e.g. iPhone Safari

function showUI() {
  document.body.classList.add("ui");
  clearTimeout(uiTimer);
  uiTimer = setTimeout(() => document.body.classList.remove("ui"), 4000);
}
document.addEventListener("mousemove", (e) => { if (e.movementX || e.movementY) showUI(); });
// touch: tap shows the controls, swipe up/down changes channel (only while watching here)
let touchStart = null;
const overlayOpen = () => castDev || REMOTE_ONLY || $("#guide").classList.contains("on") || $("#castpick").classList.contains("on");
document.addEventListener("touchstart", (e) => { touchStart = e.target.closest("#controls, #guide, #castpick, #remote, #power, #lock") ? null : e.touches[0].clientY; }, { passive: true });
document.addEventListener("touchend", (e) => {
  if (touchStart === null || overlayOpen()) return;
  const dy = e.changedTouches[0].clientY - touchStart; touchStart = null;
  if (Math.abs(dy) > 60) action(dy < 0 ? "up" : "down");
  else if (document.body.classList.contains("ui")) document.body.classList.remove("ui");
  else { showUI(); showBanner(); }
});

// ---------------------------------------------------------------- start
function toast(text) {
  const m = $("#msg"); m.textContent = text; m.style.display = "block";
  setTimeout(() => { if (m.textContent === text) m.style.display = "none"; }, 3500);
}
// ---------------------------------------------------------------- screen off (sleep): black picture, sound keeps going
let dark = false, darkHintTimer = null, sleepTimer = null;
function screenOff(off, why) {
  if (off && (castDev || REMOTE_ONLY)) { toast("Screen off works when the channel is playing on this screen"); return; }
  if (!!off !== dark) clog(off ? "screen off" : "screen on", why || (off ? "button" : "key"));
  dark = !!off;
  const b = $("#blackout");
  b.classList.toggle("on", dark);
  clearTimeout(darkHintTimer);
  if (dark) {
    toggleGuide(false);
    $("#banner").classList.remove("on");
    document.body.classList.remove("ui");
    $("#wakehint").textContent = APP ? "Press any button on the remote to turn the picture back on" : "Press any key or tap the screen to turn the picture back on";
    $(".hint", b).classList.remove("gone");
    darkHintTimer = setTimeout(() => $(".hint", b).classList.add("gone"), 4000);   // then truly black
  } else {
    armSleep();          // on a sleep channel the screen goes dark again after its delay
  }
}
$("#blackout").addEventListener("click", (e) => { e.stopPropagation(); screenOff(false); });
$("#blackout").addEventListener("touchend", (e) => { e.preventDefault(); e.stopPropagation(); screenOff(false); });
// sleep channels: the screen turns itself off a few minutes after you tune in or last touch anything
function armSleep() {
  clearTimeout(sleepTimer);
  const ch = channels[idx], mins = ch && +ch.screen_off_minutes;
  if (!mins || castDev || REMOTE_ONLY || dark) return;
  sleepTimer = setTimeout(() => {
    const cur = channels[idx];
    if (cur && cur.id === ch.id && !$("#guide").classList.contains("on") && !$("#lock").classList.contains("on"))
      screenOff(true, `sleep channel ${ch.number} after ${mins} min`);
    else armSleep();
  }, mins * 60000);
}
["keydown", "click", "touchstart"].forEach((ev) => document.addEventListener(ev, () => { if (!dark && sleepTimer) armSleep(); }, true));

async function powerOn() {
  if (on) return;
  on = true;
  $("#power").remove();
  await Promise.all([loadChannels(), refreshLock()]);
  if (!channels.length) { $("#msg").textContent = "No channels are on the air yet."; $("#msg").style.display = "block"; return; }
  let want = decodeURIComponent(location.hash.slice(1)) || store.get("jfb-last");
  const i0 = channels.findIndex((c) => String(c.number) === String(want));
  idx = i0 >= 0 ? i0 : 0;
  try {   // were we the remote for a Chromecast last time? pick up where we left off if it's still showing our channel
    const saved = JSON.parse(store.get("jfb-cast") || "null");
    if (saved) {
      const d = await capi("devices");
      const dev = (d.devices || []).find((x) => x.id === saved.id);
      if (dev && dev.channel) return attach(dev, dev.channel);
    }
  } catch { }
  if (REMOTE_ONLY) return openCastPicker();
  tune(idx);
  showUI();
  setInterval(() => { if ($("#guide").classList.contains("on")) toggleGuide(true); }, 30000);
  setInterval(() => { if (!document.hidden && nowInfoStale(channels[idx])) loadChannels().catch(() => { }); }, 30000);
}
if (APP) $("#guide .hint").textContent = "▲▼ choose · OK watch · Back close";
if (REMOTE_ONLY || APP) {
  // no video on the phone / the TV app may autoplay: no need to wait for a tap before starting
  powerOn();
} else {
  $("#power").onclick = powerOn;
}
updateMuteIcons();
