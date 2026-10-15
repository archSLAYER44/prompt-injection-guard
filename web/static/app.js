/* Injection Guard web pages: the shared shell, the API client and the components every page draws.
   Every value shown comes from the API (the detector, the shared log, the report files). */

const API = {
  get: (p) => fetch(p).then(r => r.ok ? r.json() : r.json().then(e => { throw new Error(e.detail || r.statusText); })),
  post: (p, body) => fetch(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) })
    .then(r => r.ok ? r.json() : r.json().then(e => { throw new Error(e.detail || r.statusText); })),
};
const GREEN = "#73BF69", RED = "#F2495C", YELLOW = "#FADE2A", BLUE = "#5794F2", GRID = "#292a2f", MUTED = "#8c919d";
const SESSION = (() => {
  let s = localStorage.getItem("ig_session");
  if (!s) { s = Math.random().toString(16).slice(2, 10); localStorage.setItem("ig_session", s); }
  return s;
})();
const SETTINGS_KEY = "ig_settings";

function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function icon(name, cls = "text-[16px]") { return `<span class="material-symbols-outlined ${cls}">${name}</span>`; }
function fmtScore(x) { return (x >= 0 ? "+" : "") + Number(x).toFixed(2); }
function fmtScore3(x) { return (x >= 0 ? "+" : "") + Number(x).toFixed(3); }
function fmtMs(x) { return x == null ? "–" : `${Math.round(x)} ms`; }
function zone(score, thr) { return score >= thr ? "bad" : (score >= thr - 0.35 * (thr + 5) ? "warn" : "ok"); }
function zoneColour(score, dist) {
  if (!dist) return score >= 0.546 ? RED : GREEN;
  const lo = dist.scale.min, thr = dist.scale.threshold, g = lo + 0.35 * (thr - lo);
  return score < g ? GREEN : (score < thr ? YELLOW : RED);
}
function median(a) { if (!a.length) return null; const s = [...a].sort((x, y) => x - y); const m = Math.floor(s.length / 2); return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; }

function loadSettings() {
  try { return Object.assign({ provider: "Stub (built-in, no model)", model: "", base_url: "", api_key: "", guard_on: true, threshold: null }, JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}")); }
  catch (e) { return { provider: "Stub (built-in, no model)", model: "", base_url: "", api_key: "", guard_on: true, threshold: null }; }
}
function saveSettings(s) { const copy = { ...s }; delete copy.api_key; localStorage.setItem(SETTINGS_KEY, JSON.stringify(copy)); }

// ---------------------------------------------------------------- badges and chips (icon + label, never colour alone)
const KINDS = {
  ok: { cls: "bg-secondary-container/30 text-secondary", icon: "check_circle" },
  bad: { cls: "bg-tertiary-container/20 text-tertiary", icon: "gpp_maybe" },
  warn: { cls: "bg-[#FADE2A]/15 text-[#FADE2A]", icon: "warning" },
  info: { cls: "bg-primary/10 text-primary", icon: "info" },
  neutral: { cls: "bg-surface-container text-on-surface-variant", icon: "" },
};
function badge(kind, text, iconName) {
  const k = KINDS[kind] || KINDS.neutral;
  const ic = iconName === "" ? "" : icon(iconName || k.icon, "text-[13px]");
  return `<span class="inline-flex items-center gap-1 px-space-xs py-space-2xs rounded text-badge-label font-mono-data font-medium uppercase tracking-wide whitespace-nowrap ${k.cls}">${ic}${esc(text)}</span>`;
}
function chip(iconName, label, value, valueCls = "text-on-surface") {
  return `<div class="flex items-center gap-space-xs px-space-sm py-space-xs rounded bg-surface-container-lowest font-mono-data text-badge-label">${icon(iconName, "text-[14px] text-outline")}<span class="text-on-surface-variant">${esc(label)}</span><span class="${valueCls} font-medium truncate max-w-[220px]">${esc(value)}</span></div>`;
}
function tile({ label, value, sub, note, icon: ic, kind = "info", colour }) {
  const col = colour || { ok: GREEN, bad: RED, warn: YELLOW, info: BLUE, neutral: MUTED }[kind];
  const noteCls = { ok: "text-secondary", bad: "text-tertiary", warn: "text-[#FADE2A]", info: "text-primary", neutral: "text-outline" }[kind];
  return `<div class="bg-surface-container-low p-space-md rounded flex flex-col gap-space-2xs border-l-[3px]" style="border-left-color:${col}">
    <div class="flex items-center justify-between"><span class="font-panel-title text-panel-title text-outline">${esc(label)}</span>${icon(ic || "analytics", "text-[18px] " + noteCls)}</div>
    <div class="flex items-baseline gap-space-xs"><span class="font-mono-metric text-mono-metric text-on-surface truncate" title="${esc(value)}">${esc(value)}</span>${note ? `<span class="font-mono-data text-badge-label ${noteCls} font-medium">${esc(note)}</span>` : ""}</div>
    <div class="font-mono-data text-badge-label text-outline truncate">${esc(sub || "")}</div></div>`;
}
function panelTitle(iconName, title, right) {
  return `<div class="flex items-center justify-between mb-space-sm"><div class="flex items-center gap-space-xs">${icon(iconName, "text-[16px] text-outline")}<span class="font-panel-title text-panel-title text-outline">${esc(title)}</span></div>${right ? `<span class="font-mono-data text-badge-label text-outline bg-surface-container px-space-xs py-space-2xs rounded">${right}</span>` : ""}</div>`;
}

// ---------------------------------------------------------------- the shell: header bar, profile line, navigation rail
const NAV = [["monitoring", "query_stats", "Monitoring"], ["history", "history", "History"], ["chat", "science", "Test console"], ["inspector", "policy", "Guard inspector"],
             ["results", "fact_check", "Results"], ["about", "info", "About"]];
function chatAppLink(conversation) { return `${(window.STATUS && window.STATUS.chat_app_url) || "http://localhost:8001"}/?c=${encodeURIComponent(conversation)}`; }
async function shell(active) {
  const host = document.getElementById("shell");
  host.innerHTML = `
<header class="fixed top-0 left-0 right-0 z-50 bg-surface-container-low">
  <div class="h-12 w-full px-margin flex items-center justify-between border-b border-outline-variant/40">
    <div class="flex items-center gap-space-sm">
      ${icon("shield", "text-[22px] text-primary")}
      <span class="font-headline-lg text-headline-lg text-on-surface tracking-tight font-semibold">Injection Guard</span>
      <span class="px-space-xs py-space-2xs bg-surface-container font-mono-data text-badge-label text-on-surface-variant rounded border border-outline-variant/30" id="hdr-round">…</span>
      <div class="flex items-center gap-space-xs ml-space-xs px-space-xs py-space-2xs rounded bg-surface-container-lowest border border-secondary-container/40">
        <span class="relative flex h-2 w-2"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-secondary opacity-75"></span><span class="relative inline-flex rounded-full h-2 w-2 bg-secondary"></span></span>
        <span class="font-badge-label text-badge-label text-secondary font-medium uppercase tracking-wide" id="hdr-live">detector live</span>
      </div>
    </div>
    <div class="flex items-center gap-space-md">
      <div class="hidden sm:flex items-center gap-space-xs bg-surface-container-lowest border border-outline-variant/40 rounded px-space-sm py-space-2xs">${icon("memory", "text-outline text-[16px]")}<span class="font-mono-data text-body-sm text-on-surface-variant" id="hdr-model">…</span></div>
      <div class="flex items-center gap-space-xs bg-surface-container-lowest border border-outline-variant/40 rounded px-space-sm py-space-2xs">${icon("speed", "text-secondary text-[16px]")}<span class="font-mono-data text-body-sm text-secondary" id="hdr-ms">–</span></div>
      <div class="flex items-center gap-space-xs bg-surface-container-lowest border border-outline-variant/40 rounded px-space-sm py-space-2xs">${icon("terminal", "text-outline text-[16px]")}<span class="font-mono-data text-body-sm text-on-surface-variant" id="hdr-session">${esc(SESSION)}</span></div>
    </div>
  </div>
  <div class="h-8 w-full px-margin bg-surface-container-lowest border-b border-outline-variant/30 flex items-center justify-between font-mono-data text-body-sm">
    <div class="flex items-center gap-space-sm overflow-hidden">${icon("tune", "text-outline text-[15px]")}<span class="text-outline">Active profile:</span><span class="text-on-surface font-medium truncate" id="hdr-profile">…</span><span class="text-outline-variant">/</span><span class="px-space-xs py-space-2xs rounded bg-surface-container border border-outline-variant/40 text-primary text-badge-label font-mono-data uppercase" id="hdr-thr">…</span></div>
    <div class="hidden md:flex items-center gap-space-lg text-badge-label text-outline"><span class="flex items-center gap-space-xs"><span class="w-1.5 h-1.5 rounded-full bg-secondary"></span><span id="hdr-log">log: …</span></span><span class="flex items-center gap-space-xs"><span class="w-1.5 h-1.5 rounded-full bg-primary"></span>inspection: 9 stages per request</span></div>
  </div>
</header>
<aside class="w-60 shrink-0 bg-surface-container-low border-r border-outline-variant/30 min-h-screen pt-24 px-space-sm pb-space-md hidden lg:flex flex-col justify-between fixed top-0 left-0 bottom-0 z-40">
  <div class="flex flex-col gap-space-sm">
    <div class="flex items-center justify-between px-space-sm py-space-xs text-outline font-mono-data text-badge-label uppercase tracking-wider"><span>Observability suite</span>${icon("tune", "text-[16px]")}</div>
    <nav class="flex flex-col gap-space-2xs mt-space-xs">${NAV.map(([p, ic, label]) => `<a href="/${p}" class="flex items-center gap-space-sm px-space-sm py-space-xs rounded font-panel-title text-panel-title transition-colors ${p === active ? "bg-surface-container text-primary font-medium border-l-2 border-primary" : "hover:bg-surface-container text-on-surface-variant hover:text-on-surface"}">${icon(ic, "text-[18px]" + (p === active ? " text-primary" : ""))}<span>${label}</span></a>`).join("")}</nav>
  </div>
  <div class="px-space-sm py-space-xs border-t border-outline-variant/30 flex flex-col gap-space-2xs font-mono-data text-[10px] text-outline">
    <a class="flex items-center justify-between py-space-2xs text-on-surface-variant hover:text-primary" href="http://localhost:8001/" id="side-chat-app" target="_blank" rel="noopener"><span>CHAT APP (SEPARATE SITE)</span>${icon("open_in_new", "text-[14px]")}</a>
    <div class="flex items-center justify-between"><span>DETECTOR</span><span class="text-secondary" id="side-status">loading</span></div>
    <div class="flex items-center justify-between"><span>REQUESTS LOGGED</span><span class="text-on-surface" id="side-count">–</span></div>
    <div class="flex items-center justify-between"><span>BLOCKED</span><span class="text-tertiary" id="side-blocked">–</span></div>
  </div>
</aside>`;
  try {
    const st = await API.get("/api/status");
    window.STATUS = st;
    const emb = st.embedding.model.split("/").pop();
    document.getElementById("hdr-round").textContent = st.round;
    document.getElementById("hdr-model").textContent = `${emb} + ${st.rules} rules`;
    document.getElementById("hdr-profile").textContent = `${emb} (${st.embedding.dimension}-d) + ${st.rules} rules · linear SVM C=0.3`;
    document.getElementById("hdr-thr").textContent = `threshold ${st.threshold.toFixed(3)}`;
    document.getElementById("hdr-log").textContent = `log: ${st.log.requests} request(s) · ${st.log.sessions} session(s)`;
    document.getElementById("side-status").textContent = "ready";
    if (st.chat_app_url) document.getElementById("side-chat-app").href = st.chat_app_url + "/";
    document.getElementById("side-count").textContent = st.log.requests;
    document.getElementById("side-blocked").textContent = st.log.blocked;
    return st;
  } catch (e) {
    document.getElementById("side-status").textContent = "API unreachable";
    document.getElementById("hdr-live").textContent = "API unreachable";
    throw e;
  }
}
function setHeaderMs(ms) { const el = document.getElementById("hdr-ms"); if (el) el.textContent = fmtMs(ms); }
async function refreshSideCounts() {
  try { const st = await API.get("/api/status"); document.getElementById("side-count").textContent = st.log.requests; document.getElementById("side-blocked").textContent = st.log.blocked;
        document.getElementById("hdr-log").textContent = `log: ${st.log.requests} request(s) · ${st.log.sessions} session(s)`; } catch (e) {}
}

// ---------------------------------------------------------------- chat turns (from design/stitch/production_chat)
function turnHTML(row, opts = {}) {
  const thr = row.threshold ?? (window.STATUS ? window.STATUS.threshold : 0.546);
  const flagged = row.verdict === "injection";
  const userMeta = row.blocked === "yes"
    ? `<div class="flex items-center gap-space-xs font-mono-data text-badge-label text-error mb-space-2xs">${icon("gpp_maybe", "text-[13px] text-error")}<span>attack flagged</span><span>•</span><span>${esc(row.time)}</span></div>`
    : `<div class="flex items-center gap-space-xs font-mono-data text-badge-label text-outline mb-space-2xs"><span>You</span><span>•</span><span>${esc(row.time)}</span>${icon(flagged ? "warning" : "verified", "text-[13px] " + (flagged ? "text-[#FADE2A]" : "text-secondary"))}</div>`;
  const doc = row._document ? `<div class="flex items-center gap-space-xs text-badge-label font-mono-data text-outline mt-space-2xs max-w-2xl">${icon("description", "text-[12px] text-primary")}<span class="truncate">retrieved document · ${esc(row._document.slice(0, 120))}${row._document.length > 120 ? "…" : ""}</span></div>` : "";
  const user = `<div class="flex flex-col items-end gap-space-2xs ml-8 sm:ml-20">${userMeta}
    <div class="p-space-md rounded ${row.blocked === "yes" ? "bg-error-container/20" : "bg-primary-container/15"} text-on-surface font-body-default text-body-default max-w-2xl shadow-sm msg-body">${esc(row._message)}</div>${doc}
    <div class="flex items-center gap-space-xs text-badge-label font-mono-data text-outline mt-space-2xs">${icon(flagged ? "warning" : "check", "text-[12px] " + (flagged ? "text-tertiary" : "text-secondary"))}<span>${flagged ? "flagged" : "heuristics clean"}</span><span>•</span><span class="${flagged ? "text-tertiary" : "text-secondary"}">score ${fmtScore(row.score)}</span><span>•</span><span>${fmtMs(row.scan_ms)} detector</span></div></div>`;
  let reply;
  if (row.blocked === "yes") {
    const rule = row.top_rule ? `Rule: <strong class="font-semibold">${esc(row.top_rule)}</strong>` : `<strong class="font-semibold">no rule fired: the embedding alone</strong>`;
    reply = `<div class="flex flex-col items-start gap-space-2xs mr-4 sm:mr-12 w-full"><div class="w-full bg-error-container/30 rounded p-space-md shadow-md">
      <div class="flex flex-wrap items-center justify-between gap-space-sm pb-space-sm mb-space-sm bg-error-container/20 -mx-space-md -mt-space-md px-space-md py-space-xs rounded-t">
        <div class="flex items-center gap-space-xs"><span class="px-space-xs py-space-2xs rounded bg-error font-badge-label text-badge-label text-on-error font-semibold uppercase flex items-center gap-space-2xs shadow-sm">${icon("shield", "text-[14px]")}Blocked by guard</span><span class="font-mono-data text-badge-label text-error font-medium">stage 7 decision · ${esc((row.flagged || []).join(", ").toLowerCase() || "user message")} flagged</span></div>
        <div class="flex items-center gap-space-sm font-mono-data text-badge-label"><span class="bg-surface-container-lowest px-space-xs py-space-2xs rounded text-error">Score: <strong class="font-mono-metric text-[13px] text-error">${fmtScore(row.score)}</strong> (threshold ${Number(thr).toFixed(3)})</span><span class="bg-surface-container-lowest px-space-xs py-space-2xs rounded text-error">${rule}</span></div></div>
      <div class="flex items-start gap-space-sm">${icon("report", "text-error text-[20px] shrink-0 mt-0.5")}<div class="flex flex-col gap-space-xs text-on-surface"><p class="font-body-default text-body-default leading-relaxed"><strong class="text-error font-medium">Refusal:</strong> Sorry, I can't help with that request. The message was intercepted by the injection guard before the model saw it; no reply was generated.</p>
      <div class="mt-space-xs p-space-xs bg-surface-container-lowest rounded font-mono-data text-badge-label text-outline flex flex-wrap gap-x-space-md gap-y-space-2xs"><span>Verdict: <span class="text-on-surface">injection</span></span><span>Part: <span class="text-on-surface">${esc((row.flagged || []).join(", ") || "user message")}</span></span><span>Action: <span class="text-error">not sent to the model</span></span><span>Detector: <span class="text-on-surface">${fmtMs(row.scan_ms)}</span></span></div></div></div></div>
      <div class="flex items-center gap-space-xs text-badge-label font-mono-data text-outline pl-space-xs mt-space-2xs">${icon("block", "text-[13px] text-error")}<span>nothing left the guard · the chat model was not called</span></div></div>`;
  } else if (row._error) {
    reply = `<div class="flex flex-col items-start gap-space-2xs mr-8 sm:mr-20"><div class="flex items-center gap-space-xs font-mono-data text-badge-label text-outline mb-space-2xs"><div class="w-2 h-2 rounded-full bg-[#FADE2A]"></div><span class="text-on-surface font-medium">Assistant</span><span>•</span><span>model error</span></div><div class="p-space-md rounded bg-surface-container text-on-surface font-body-default text-body-default max-w-2xl shadow-sm msg-body">${esc(row._error)}</div></div>`;
  } else {
    const leak = row["reply contains secret"] === "yes" ? badge("bad", "secret leaked", "gpp_maybe") : `<span class="px-space-xs py-space-2xs rounded bg-surface-container font-mono-data text-badge-label text-secondary">passed gate${row.guard === "on" ? "" : " (guard off)"}</span>`;
    reply = `<div class="flex flex-col items-start gap-space-2xs mr-8 sm:mr-20"><div class="flex items-center gap-space-xs font-mono-data text-badge-label text-outline mb-space-2xs"><div class="w-2 h-2 rounded-full bg-secondary"></div><span class="text-on-surface font-medium">Assistant</span><span>•</span><span>${esc(row.time)}</span>${leak}</div>
      <div class="p-space-md rounded bg-surface-container text-on-surface font-body-default text-body-default max-w-2xl shadow-sm leading-relaxed msg-body">${esc(row._reply || "")}</div>
      <div class="flex items-center gap-space-sm font-mono-data text-badge-label text-outline mt-space-2xs"><span class="flex items-center gap-space-2xs">${icon("memory", "text-[12px]")} ${esc(row.provider)}</span><span>•</span><span class="flex items-center gap-space-2xs">${icon("timer", "text-[12px]")} ${Number(row.elapsed || 0).toFixed(1)} s reply</span>${row["reply contains secret"] === "yes" ? `<span>•</span><span class="text-error">the secret word appears in the reply</span>` : ""}</div></div>`;
  }
  return user + reply;
}

// ---------------------------------------------------------------- charts (inline SVG, drawn from real numbers)
function histogramSVG(dist, score, opts = {}) {
  const W = 700, H = 220, L = 35, R = 665, T = 15, B = 180;
  const lo = dist.scale.min, hi = dist.scale.max, thr = dist.scale.threshold;
  const edges = dist.bins.edges, centers = edges.slice(0, -1).map((a, i) => (a + edges[i + 1]) / 2);
  const ymax = Math.max(...dist.bins.benign, ...dist.bins.injection) * 1.12;
  const X = v => L + (R - L) * (Math.min(Math.max(v, lo), hi) - lo) / (hi - lo), Y = v => B - (B - T) * v / ymax;
  const path = (vals) => centers.map((c, i) => `${i ? "L" : "M"} ${X(c).toFixed(1)},${Y(vals[i]).toFixed(1)}`).join(" ");
  const area = (vals) => `${path(vals)} L ${X(centers[centers.length - 1]).toFixed(1)},${B} L ${X(centers[0]).toFixed(1)},${B} Z`;
  const g = lo + 0.35 * (thr - lo);
  const marker = score == null ? "" : `<line stroke="#ffffff" stroke-width="2.5" x1="${X(score).toFixed(1)}" x2="${X(score).toFixed(1)}" y1="12" y2="${B}"></line>
    <rect fill="#1e1f25" height="18" rx="2" stroke="#ffffff" stroke-width="1" width="104" x="${(X(score) + (score > thr ? -112 : 8)).toFixed(1)}" y="30"></rect>
    <text fill="#ffffff" font-family="monospace" font-size="10" font-weight="600" text-anchor="middle" x="${(X(score) + (score > thr ? -60 : 60)).toFixed(1)}" y="43">Current ${fmtScore(score)}</text>`;
  const ticks = [];
  for (let v = Math.ceil(lo / 2) * 2; v <= hi; v += 2) ticks.push(`<text fill="#8c919d" font-family="monospace" font-size="9" text-anchor="middle" x="${X(v).toFixed(1)}" y="${B + 14}">${v}</text>`);
  return `<svg class="w-full ${opts.compact ? "h-40" : "h-48 sm:h-56"} select-none" preserveAspectRatio="none" viewBox="0 0 ${W} ${H}">
    <defs><linearGradient id="bg1" x1="0%" x2="0%" y1="0%" y2="100%"><stop offset="0%" stop-color="#8bd980" stop-opacity="0.32"></stop><stop offset="100%" stop-color="#8bd980" stop-opacity="0.02"></stop></linearGradient>
    <linearGradient id="ig1" x1="0%" x2="0%" y1="0%" y2="100%"><stop offset="0%" stop-color="#ff5a6a" stop-opacity="0.35"></stop><stop offset="100%" stop-color="#ff5a6a" stop-opacity="0.02"></stop></linearGradient></defs>
    <rect x="${L}" y="${T}" width="${(X(g) - L).toFixed(1)}" height="${B - T}" fill="${GREEN}" opacity="0.05"></rect><rect x="${X(g).toFixed(1)}" y="${T}" width="${(X(thr) - X(g)).toFixed(1)}" height="${B - T}" fill="${YELLOW}" opacity="0.05"></rect><rect x="${X(thr).toFixed(1)}" y="${T}" width="${(R - X(thr)).toFixed(1)}" height="${B - T}" fill="${RED}" opacity="0.05"></rect>
    ${[30, 80, 130].map(y => `<line stroke="#2c3235" stroke-dasharray="3 3" stroke-width="1" x1="${L}" x2="${R}" y1="${y}" y2="${y}"></line>`).join("")}<line stroke="#424752" stroke-width="1.2" x1="${L}" x2="${R}" y1="${B}" y2="${B}"></line>
    <path d="${area(dist.bins.benign)}" fill="url(#bg1)"></path><path d="${path(dist.bins.benign)}" fill="none" stroke="#8bd980" stroke-width="2"></path>
    <path d="${area(dist.bins.injection)}" fill="url(#ig1)"></path><path d="${path(dist.bins.injection)}" fill="none" stroke="#ff5a6a" stroke-width="2"></path>
    <line stroke="#FADE2A" stroke-dasharray="4 4" stroke-width="2" x1="${X(thr).toFixed(1)}" x2="${X(thr).toFixed(1)}" y1="15" y2="${B}"></line>
    <rect fill="#1e1f25" height="18" rx="2" stroke="#FADE2A" stroke-width="1" width="104" x="${(X(thr) - 52).toFixed(1)}" y="8"></rect><text fill="#FADE2A" font-family="monospace" font-size="10" font-weight="600" text-anchor="middle" x="${X(thr).toFixed(1)}" y="21">Threshold ${thr.toFixed(3)}</text>
    ${marker}${ticks.join("")}<text fill="#8c919d" font-family="monospace" font-size="9" x="${L}" y="${H - 2}">detector score (SVM decision value)</text></svg>`;
}
function percentileBelow(dist, cls, score) {
  const p = dist.quantiles.percent, v = dist.quantiles[cls];
  if (score <= v[0]) return 0; if (score >= v[v.length - 1]) return 100;
  for (let i = 1; i < v.length; i++) if (score < v[i]) { const t = (score - v[i - 1]) / ((v[i] - v[i - 1]) || 1e-9); return p[i - 1] + t * (p[i] - p[i - 1]); }
  return 100;
}
function zoneBar(dist, score) {
  const lo = dist.scale.min, hi = dist.scale.max, thr = dist.scale.threshold, g = lo + 0.35 * (thr - lo), w = v => 100 * v / (hi - lo);
  const ptr = score == null ? "" : `<div class="absolute -bottom-2 w-0 h-0 border-l-[6px] border-r-[6px] border-b-[8px] border-l-transparent border-r-transparent border-b-white" style="left:${(100 * (Math.min(Math.max(score, lo), hi) - lo) / (hi - lo)).toFixed(2)}%;transform:translateX(-50%)"></div>`;
  return `<div class="relative mt-space-sm mb-space-md"><div class="flex h-2 rounded overflow-hidden"><div style="width:${w(g - lo).toFixed(2)}%;background:${GREEN}"></div><div style="width:${w(thr - g).toFixed(2)}%;background:${YELLOW}"></div><div style="width:${w(hi - thr).toFixed(2)}%;background:${RED}"></div></div>${ptr}</div>`;
}
function sparklineSVG(rows, thr, dist) {
  const W = 380, H = 180, L = 36, R = 372, T = 16, B = 160;
  const scores = rows.map(r => r.score);
  if (!scores.length) return `<div class="font-mono-data text-badge-label text-outline p-space-md">no requests yet</div>`;
  const lo = Math.min(-3, ...scores, thr - 1), hi = Math.max(3, ...scores, thr + 1);
  const X = i => rows.length === 1 ? (L + R) / 2 : L + (R - L) * i / (rows.length - 1), Y = v => B - (B - T) * (v - lo) / (hi - lo);
  const line = scores.map((s, i) => `${i ? "L" : "M"} ${X(i).toFixed(1)} ${Y(s).toFixed(1)}`).join(" ");
  const dots = scores.map((s, i) => `<circle cx="${X(i).toFixed(1)}" cy="${Y(s).toFixed(1)}" r="3.5" fill="${zoneColour(s, dist)}" opacity="0.95"><title>${esc(rows[i].message)} · ${fmtScore(s)}</title></circle>`).join("");
  const gridY = [], labels = [];
  for (let v = Math.ceil(lo / 2) * 2; v <= hi; v += 2) { gridY.push(`<line stroke="${GRID}" stroke-width="1" x1="${L}" x2="${R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"></line>`); labels.push(`<text fill="#8c919d" font-family="monospace" font-size="9" x="4" y="${(Y(v) + 3).toFixed(1)}">${v}</text>`); }
  return `<svg class="w-full h-full" fill="none" preserveAspectRatio="none" viewBox="0 0 ${W} ${H}">${gridY.join("")}
    <line stroke="${RED}" stroke-dasharray="4 3" stroke-width="1.5" x1="${L}" x2="${R}" y1="${Y(thr).toFixed(1)}" y2="${Y(thr).toFixed(1)}"></line><text fill="${RED}" font-family="monospace" font-size="9" x="${L + 2}" y="${(Y(thr) - 4).toFixed(1)}">THRESHOLD: ${thr.toFixed(3)}</text>
    ${labels.join("")}<path d="${line}" fill="none" stroke="#5794f2" stroke-opacity="0.45" stroke-width="1.2"></path>${dots}</svg>`;
}
function donutHTML(allowed, blocked) {
  const total = allowed + blocked, c = 2 * Math.PI * 38, a = total ? c * allowed / total : 0;
  const pct = n => total ? (100 * n / total).toFixed(1) + "%" : "–";
  return `<div class="flex items-center justify-center gap-space-lg my-auto py-space-xs"><div class="relative w-36 h-36 flex items-center justify-center">
    <svg class="w-full h-full -rotate-90" viewBox="0 0 100 100"><circle cx="50" cy="50" fill="none" r="38" stroke="#1e1f25" stroke-width="12"></circle>
    <circle cx="50" cy="50" fill="none" r="38" stroke="${GREEN}" stroke-dasharray="${a.toFixed(2)} ${c.toFixed(2)}" stroke-linecap="${allowed && blocked ? "round" : "butt"}" stroke-width="12"></circle>
    <circle cx="50" cy="50" fill="none" r="38" stroke="${RED}" stroke-dasharray="${(c - a).toFixed(2)} ${c.toFixed(2)}" stroke-dashoffset="${(-a).toFixed(2)}" stroke-linecap="${allowed && blocked ? "round" : "butt"}" stroke-width="12"></circle></svg>
    <div class="absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none"><span class="font-mono-metric text-mono-metric text-on-surface font-semibold">${total}</span><span class="font-mono-data text-badge-label text-outline uppercase tracking-wider">requests</span></div></div>
    <div class="flex flex-col gap-space-sm font-mono-data"><div class="bg-surface-container-lowest p-space-xs rounded"><div class="flex items-center gap-space-xs text-badge-label text-outline"><span class="w-2.5 h-2.5 rounded-sm bg-secondary inline-block"></span><span>ALLOWED</span></div><div class="text-body-default font-semibold text-secondary mt-0.5">${pct(allowed)}</div><div class="text-badge-label text-on-surface-variant">${allowed} request(s)</div></div>
    <div class="bg-surface-container-lowest p-space-xs rounded"><div class="flex items-center gap-space-xs text-badge-label text-outline"><span class="w-2.5 h-2.5 rounded-sm bg-tertiary inline-block"></span><span>BLOCKED</span></div><div class="text-body-default font-semibold text-tertiary mt-0.5">${pct(blocked)}</div><div class="text-badge-label text-on-surface-variant">${blocked} request(s)</div></div></div></div>`;
}
function rulesBarsHTML(rows, ruleNames, descriptive) {
  const counts = {}; ruleNames.filter(n => !descriptive.includes(n)).forEach(n => counts[n] = 0);
  rows.forEach(r => (r._fired || []).forEach(n => { if (n in counts) counts[n] += 1; }));
  const ordered = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const top = Math.max(1, ...ordered.map(e => e[1]));
  return ordered.map(([k, v], i) => `<div class="flex flex-col gap-1"><div class="flex items-center justify-between font-mono-data text-body-sm"><span class="text-on-surface font-medium truncate">${esc(k)}</span><span class="${v ? (i < 3 ? "text-tertiary" : "text-primary") : "text-outline"} font-semibold">${v}</span></div><div class="w-full bg-surface-container h-2 rounded overflow-hidden"><div class="h-full rounded" style="width:${(100 * v / top).toFixed(0)}%;background-color:${v ? (i < 3 ? RED : BLUE) : "transparent"}"></div></div></div>`).join("");
}
function tableRowsHTML(rows, { live = true, filter = "all", query = "", expandable = false, open = null } = {}) {
  const q = query.trim().toLowerCase();
  const shown = rows.filter(r => (filter === "all" || (filter === "blocked") === (r.blocked === "yes")) && (!q || (r._message || "").toLowerCase().includes(q) || (r.session || "").includes(q) || (r.conversation || "").includes(q) || (r.top_rule || "").includes(q)));
  const html = [...shown].reverse().map((r, i) => {
    const idx = rows.indexOf(r);
    const verdict = r.blocked === "yes" ? badge("bad", "blocked", "gpp_maybe") : (r.verdict === "injection" ? badge("warn", "flagged, sent", "warning") : badge("ok", "allowed", "check_circle"));
    const reply = r["reply contains secret"] === "yes" ? badge("bad", "secret leaked", "gpp_maybe") : (r.blocked === "yes" ? badge("neutral", "not sent", "") : (r._error ? badge("warn", "error", "warning") : badge("ok", "clean", "check")));
    const isOpen = open && open.has(idx);
    return `<tr class="hover:bg-surface-container/60 transition-colors ${expandable ? "cursor-pointer" : ""} ${isOpen ? "bg-surface-container/40" : ""}" ${expandable ? `data-detail="${idx}"` : ""}><td class="py-space-xs px-space-sm text-outline whitespace-nowrap">${expandable ? icon(isOpen ? "expand_less" : "expand_more", "text-[16px] text-outline mr-1") : ""}${esc(r.time)}</td>
      ${live ? `<td class="py-space-xs px-space-sm whitespace-nowrap"><span class="px-space-xs py-space-2xs rounded ${["chat", "inspector", "dashboard"].includes(r.surface) ? "bg-primary/10 text-primary" : "bg-secondary/10 text-secondary"} text-badge-label">${esc(r.surface || "?")}</span></td><td class="py-space-xs px-space-sm font-semibold text-primary whitespace-nowrap">${esc(r.session || "")}${r.conversation ? `<a class="block font-normal text-outline hover:text-primary text-[10px]" href="${chatAppLink(r.conversation)}" target="_blank" rel="noopener" title="open this chat in the chat app">chat ${esc(r.conversation.slice(0, 8))}</a>` : ""}</td>` : ""}
      <td class="py-space-xs px-space-sm max-w-xs font-body-sm truncate text-on-surface" title="${esc(r._message)}">${r.top_rule ? `<span class="text-tertiary font-mono-data font-semibold mr-1">[${esc(r.top_rule.replace("_count", "").replace("_score", "").replace("_ratio", "").toUpperCase())}]</span>` : ""}${esc(r.message)}</td>
      <td class="py-space-xs px-space-sm text-right font-bold ${r.verdict === "injection" ? "text-tertiary" : "text-secondary"}">${fmtScore3(r.score)}</td><td class="py-space-xs px-space-sm text-center whitespace-nowrap">${verdict}</td><td class="py-space-xs px-space-sm text-center whitespace-nowrap">${reply}</td>
      <td class="py-space-xs px-space-sm text-right text-outline whitespace-nowrap">${fmtMs(r.scan_ms)}</td><td class="py-space-xs px-space-sm text-center whitespace-nowrap"><a class="px-space-xs py-1 rounded bg-surface-container text-primary hover:bg-primary hover:text-surface font-body-sm text-badge-label transition-colors inline-flex items-center gap-1" href="/inspector?replay=${idx}">${icon("visibility", "text-[13px]")} Inspect</a></td></tr>${isOpen ? `<tr class="detail-row"><td class="p-space-sm bg-surface-container-lowest" colspan="${live ? 9 : 7}">${detailPanelHTML(r, window.DIST, window.STATUS)}</td></tr>` : ""}`;
  }).join("");
  return { html, shown: shown.length };
}

/* The per-message snapshot the History page shows: the monitoring page's charts and tiles for one request.
   Works from a log row alone (score, threshold, _fired) and shows more when the row carries snapshot(): _parts, _rules. */
function detailPanelHTML(r, dist, st) {
  const thr = Number(r.threshold ?? (st ? st.threshold : 0.546));
  const score = Number(r.score);
  const blocked = r.blocked === "yes", flagged = r.verdict === "injection", leaked = r["reply contains secret"] === "yes";
  const parts = r._parts || [], rules = r._rules || {};
  const ruleName = n => (n || "").replace(/_(count|score|ratio)$/, "").replace(/_/g, " ");
  const pb = dist ? percentileBelow(dist, "benign", score) : null, pi = dist ? percentileBelow(dist, "injection", score) : null;
  const chart = dist ? `<div class="bg-surface-container-lowest rounded border border-outline-variant/20 p-space-xs overflow-hidden">${histogramSVG(dist, score, { compact: true })}${zoneBar(dist, score)}</div>
      <div class="font-mono-data text-body-sm text-on-surface-variant">Score <b class="text-on-surface">${fmtScore(score)}</b> is above <b class="text-secondary">${pb.toFixed(1)}%</b> of benign and <b class="text-tertiary">${pi.toFixed(1)}%</b> of injection training scores · threshold ${thr.toFixed(3)} · ${fmtScore3(score - thr)} from it</div>`
    : `<div class="font-mono-data text-body-sm text-outline">score distribution not loaded</div>`;
  const tiles =
    tile({ label: "Score", value: fmtScore(score), note: `thr ${thr.toFixed(3)}`, sub: flagged ? "at or above the threshold" : "below the threshold", icon: "analytics", kind: flagged ? "bad" : "ok" }) +
    tile({ label: "Action", value: blocked ? "BLOCKED" : (flagged ? "SENT" : "ALLOWED"), note: blocked ? "guard on" : (flagged ? "guard off" : ""), sub: blocked ? `${(r.flagged || []).join(", ") || "user message"} flagged` : (flagged ? "flagged but the model received it" : "clean, sent to the model"), icon: blocked ? "shield" : (flagged ? "warning" : "check_circle"), kind: blocked ? "bad" : (flagged ? "warn" : "ok") }) +
    tile({ label: "Detector", value: fmtMs(r.scan_ms), note: parts.length > 1 ? `${parts.length} parts` : "", sub: parts.length ? parts.map(p => `${p.label.toLowerCase()} ${fmtMs(p.ms)}`).join(" · ") : "explain() + predict()", icon: "speed", kind: "info" }) +
    tile({ label: "Model reply", value: blocked ? "none" : (r._error ? "error" : (leaked ? "LEAKED" : "clean")), note: r.elapsed != null && !blocked ? `${Number(r.elapsed).toFixed(1)} s` : "", sub: `${r.model && r.model !== "stub" ? r.model : (r.provider || "")}${r.turns_sent ? ` · remembered ${r.turns_sent / 2 | 0} turn(s)` : ""}`, icon: leaked ? "gpp_maybe" : "memory", kind: blocked ? "neutral" : (leaked || r._error ? "bad" : "ok") });
  const ruleRows = Object.entries(rules).sort((a, b) => b[1].value - a[1].value);
  const topVal = Math.max(1, ...ruleRows.map(([, v]) => v.value));
  const rulesHTML = ruleRows.length
    ? ruleRows.map(([k, v], i) => `<div class="flex flex-col gap-1"><div class="flex items-center justify-between font-mono-data text-body-sm"><span class="text-on-surface font-medium truncate">${esc(k)}</span><span class="${i < 3 ? "text-tertiary" : "text-primary"} font-semibold">${Number.isInteger(v.value) ? v.value : v.value.toFixed(2)}</span></div><div class="w-full bg-surface-container h-2 rounded overflow-hidden"><div class="h-full rounded" style="width:${(100 * v.value / topVal).toFixed(0)}%;background-color:${i < 3 ? RED : BLUE}"></div></div>${(v.snippets || []).length ? `<div class="font-mono-data text-badge-label text-outline truncate" title="${esc(v.snippets.join(" | "))}">${v.snippets.map(x => `“${esc(x)}”`).join(" · ")}</div>` : ""}</div>`).join("")
    : ((r._fired || []).length ? (r._fired || []).map(k => `<div class="flex items-center justify-between font-mono-data text-body-sm"><span class="text-on-surface">${esc(k)}</span><span class="text-tertiary">fired</span></div>`).join("") : `<div class="font-mono-data text-body-sm text-outline">no rule fired: the embedding alone decided</div>`);
  const partsHTML = parts.length ? parts.map(p => `<div class="flex flex-col gap-space-2xs bg-surface-container-lowest rounded p-space-sm border-l-[3px]" style="border-left-color:${p.flagged ? RED : GREEN}">
      <div class="flex items-center justify-between font-mono-data text-body-sm"><span class="text-on-surface font-medium">${esc(p.label)}</span><span class="${p.flagged ? "text-tertiary" : "text-secondary"} font-semibold">${fmtScore(p.score)} · ${esc(p.verdict || "")}</span></div>
      <div class="font-mono-data text-badge-label text-outline">${p.pieces} piece(s) scored · confidence ${(100 * p.confidence).toFixed(0)}% · P(injection) ${(100 * p.probability).toFixed(0)}% · ${fmtMs(p.ms)}${p.decoded && p.decoded.length ? ` · decoded: ${esc(p.decoded.join(", "))}` : ""}</div>
      ${p.max_piece ? `<div class="font-mono-data text-badge-label text-on-surface-variant truncate" title="${esc(p.max_piece.text)}">highest ${esc(p.max_piece.kind || "piece")} (${fmtScore(p.max_piece.score)}): “${esc(p.max_piece.text)}”</div>` : ""}</div>`).join("") : "";
  const texts = `<div class="flex flex-col gap-space-xs">
      <div><div class="font-panel-title text-panel-title text-outline mb-space-2xs">Message</div><div class="font-body-sm text-body-sm text-on-surface msg-body bg-surface-container-lowest rounded p-space-sm max-h-32 overflow-y-auto">${esc(r._message || "")}</div></div>
      ${r._document ? `<div><div class="font-panel-title text-panel-title text-outline mb-space-2xs">Retrieved document (${r._document.length} chars)</div><div class="font-mono-data text-badge-label text-on-surface-variant msg-body bg-surface-container-lowest rounded p-space-sm max-h-32 overflow-y-auto">${esc(r._document)}</div></div>` : ""}
      <div><div class="font-panel-title text-panel-title text-outline mb-space-2xs">${blocked ? "Reply" : (r._error ? "Model error" : "Model reply")}</div><div class="font-body-sm text-body-sm ${blocked ? "text-error" : "text-on-surface"} msg-body bg-surface-container-lowest rounded p-space-sm max-h-32 overflow-y-auto">${esc(blocked ? "Sorry, I can't help with that request. (the model was not called)" : (r._error || r._reply || ""))}</div></div></div>`;
  return `<div class="flex flex-col gap-space-md">
    <div class="flex flex-wrap items-center gap-space-sm font-mono-data text-badge-label text-outline">${icon("policy", "text-[16px] text-primary")}<span class="text-on-surface font-medium">Request snapshot</span><span>${esc(r.ts || r.time || "")}</span><span>·</span><span>${esc(r.surface || "")}${r.session ? ` / ${esc(r.session)}` : ""}${r.conversation ? ` / chat ${esc(r.conversation)}` : ""}</span><span>·</span><span>guard ${esc(r.guard || "on")}</span>${blocked ? badge("bad", "blocked", "gpp_maybe") : (flagged ? badge("warn", "flagged, sent", "warning") : badge("ok", "allowed", "check_circle"))}${leaked ? badge("bad", "secret leaked", "gpp_maybe") : ""}</div>
    <div class="grid grid-cols-2 xl:grid-cols-4 gap-space-sm">${tiles}</div>
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-space-md">
      <div class="lg:col-span-2 flex flex-col gap-space-xs"><div class="font-panel-title text-panel-title text-outline">Where this score sits among the training data</div>${chart}</div>
      <div class="flex flex-col gap-space-sm"><div class="flex items-center justify-between"><span class="font-panel-title text-panel-title text-outline">Rules fired on the highest-scoring part</span><span class="font-mono-data text-badge-label text-outline">${ruleRows.length || (r._fired || []).length}</span></div><div class="flex flex-col gap-space-sm max-h-64 scroll-y">${rulesHTML}</div></div>
    </div>
    ${partsHTML ? `<div class="flex flex-col gap-space-xs"><div class="font-panel-title text-panel-title text-outline">Scanned parts</div><div class="grid grid-cols-1 md:grid-cols-2 gap-space-sm">${partsHTML}</div></div>` : ""}
    ${texts}
    <div class="flex items-center gap-space-sm font-mono-data text-badge-label"><a class="text-primary hover:underline flex items-center gap-1" href="/inspector?replay=${window.LOGROWS ? window.LOGROWS.indexOf(r) : ""}">${icon("visibility", "text-[13px]")}replay in the inspector (re-scores it; adds a row)</a></div>
  </div>`;
}

// ---------------------------------------------------------------- the inspection pipeline (from design/stitch/guard_inspector)
function stageRowsHTML(scan, result) {
  const info = scan.explain, norm = info.normalization, fired = info.fired, pieces = info.pieces, emb = info.embedding, flagged = scan.flagged;
  const thr = result.demo_threshold, sent = result.reply !== null || result.error !== null;
  const decoded = (norm.decoded || []).length > 0 || norm.changed;
  const top = Object.entries(fired).sort((a, b) => b[1].value - a[1].value);
  const stages = [
    { n: "01", name: "Raw input", state: "ok", tag: "RECEIVED", note: `${scan.text.length} characters`, detail: { characters: scan.text.length, label: scan.label } },
    { n: "02", name: "Normalization", state: decoded ? "warn" : "ok", tag: decoded ? "DECODED" : "CLEAN", note: decoded ? `${(norm.decoded || []).length} decoded reading(s); the text changed` : "no leetspeak, base64, hex, rot13, reversed or split text found", detail: { before: norm.before, after: norm.after, decoded: norm.decoded } },
    { n: "03", name: "Pieces scored", state: "ok", tag: `${pieces.length} PIECES`, note: `windows, sentences and decoded readings, at most ${emb.token_limit} tokens each; the text takes its highest piece`, detail: pieces.map(p => ({ kind: p.kind, tokens: p.tokens, score: Number(p.score).toFixed(3), max: p.is_max, text: p.text })) },
    { n: "04", name: "Rules", state: top.length ? "bad" : "ok", tag: top.length ? `${top.length} FIRED` : "NONE FIRED", note: top.length ? top.map(([k, v]) => `${k} = ${Number(v.value).toFixed(3)}`).join(" · ") : "no trigger rule matched the top piece", detail: Object.fromEntries(Object.entries(info.rules).map(([k, v]) => [k, Number(v).toFixed(4)])) },
    { n: "05", name: "Embedding", state: "ok", tag: `${emb.dimension}-D`, note: `${emb.model} on the ${emb.view} view of each piece`, detail: { model: emb.model, dimension: emb.dimension, token_limit: emb.token_limit, values: "not exposed by the detector" } },
    { n: "06", name: "Score vs threshold", state: flagged ? "bad" : "ok", tag: flagged ? "ABOVE" : "BELOW", note: `${fmtScore3(info.score)} against the demo threshold ${thr.toFixed(3)} (the model's own ${Number(info.threshold).toFixed(3)})`, detail: { score: Number(info.score).toFixed(4), threshold: Number(thr).toFixed(3), confidence: Number(info.confidence).toFixed(3), probability: Number(info.probability).toFixed(3) } },
    { n: "07", name: "Decision", state: flagged && result.guard_on ? "bad" : (flagged ? "warn" : "ok"), tag: flagged && result.guard_on ? "BLOCKED" : (flagged ? "FLAGGED, SENT" : "ALLOWED"), note: `predict() says ${scan.official.verdict} at the model's own threshold, confidence ${(100 * scan.official.confidence).toFixed(1)}%`, detail: { verdict: scan.official.verdict, guard_on: result.guard_on, blocked: result.blocked } },
    { n: "08", name: "LLM request", state: sent ? "ok" : "neutral", tag: sent ? "SENT" : "BYPASSED", note: sent ? `${result.provider} · ${result.model}` : "nothing was sent to the model", detail: sent ? result.messages : { sent: false } },
    { n: "09", name: "LLM response", state: result.leaked ? "bad" : (sent ? (result.error ? "warn" : "ok") : "neutral"), tag: result.leaked ? "SECRET LEAKED" : (sent ? (result.error ? "ERROR" : "CLEAN") : "NOT SENT"), note: sent ? `${Number(result.elapsed).toFixed(1)} s · ${result.leaked ? "the reply contains the secret word" : (result.error || "the secret word does not appear in the reply")}` : "no reply was generated", detail: { reply: result.reply, error: result.error } },
  ];
  const ring = { ok: ["bg-secondary-container/30 border border-secondary text-secondary", "check"], bad: ["bg-tertiary-container/40 border border-tertiary-container text-tertiary-container animate-pulse", "warning"], warn: ["bg-[#FADE2A]/20 border border-[#FADE2A] text-[#FADE2A]", "warning"], neutral: ["bg-surface-container border border-outline-variant text-outline", "remove"] };
  const tagCls = { ok: "text-secondary bg-secondary-container/20", bad: "text-on-tertiary bg-tertiary-container font-bold", warn: "text-[#FADE2A] bg-[#FADE2A]/15", neutral: "text-outline bg-surface-container" };
  return stages.map((s, i) => `<div class="pipeline-stage relative flex gap-space-md ${i < stages.length - 1 ? "pb-space-md" : ""}"><div class="flex flex-col items-center"><div class="w-7 h-7 rounded-full flex items-center justify-center shrink-0 z-10 shadow-sm ${ring[s.state][0]}">${icon(ring[s.state][1], "text-[15px]")}</div>${i < stages.length - 1 ? `<div class="w-0.5 h-full bg-outline-variant/40 mt-1"></div>` : ""}</div>
    <div class="flex-1 bg-surface-container-lowest p-space-sm rounded border ${s.state === "bad" ? "border-tertiary-container/40" : "border-outline-variant/30"} hover:border-outline-variant/60 transition-colors"><div class="flex items-center justify-between cursor-pointer stage-toggle" onclick="this.nextElementSibling.nextElementSibling.classList.toggle('hidden');this.querySelector('.material-symbols-outlined.arrow').classList.toggle('open')"><div class="flex items-center gap-space-sm"><span class="font-mono-data text-badge-label text-outline">${s.n}</span><span class="font-panel-title text-body-sm ${s.state === "bad" ? "text-tertiary-container" : "text-on-surface"} font-medium">${s.name}</span><span class="font-badge-label text-badge-label px-space-xs py-space-2xs rounded ${tagCls[s.state]}">${esc(s.tag)}</span></div><div class="flex items-center gap-space-xs">${icon("expand_more", "arrow text-outline text-[16px] transition-transform")}</div></div>
    <p class="font-body-sm text-body-sm ${s.state === "bad" ? "text-tertiary-container font-medium" : "text-on-surface-variant"} mt-space-2xs">${esc(s.note)}</p>
    <div class="stage-details hidden mt-space-sm pt-space-xs border-t border-outline-variant/20 font-mono-data text-badge-label text-outline bg-surface-container/40 p-space-xs rounded whitespace-pre-wrap break-words max-h-64 scroll-y">${esc(JSON.stringify(s.detail, null, 1))}</div></div></div>`).join("");
}

// ---------------------------------------------------------------- provider settings (chat page and inspector)
function settingsHTML(st, s) {
  const opts = st.providers.map(p => `<option value="${esc(p.name)}" ${p.name === s.provider ? "selected" : ""}>${esc(p.name)}</option>`).join("");
  return `<div class="flex flex-col gap-space-sm font-body-sm text-body-sm">
    <label class="flex flex-col gap-space-2xs"><span class="font-mono-data text-badge-label text-outline uppercase">Chat model</span><select id="set-provider" class="bg-surface-container-lowest border border-outline-variant/40 rounded p-space-xs font-mono-data text-body-sm text-on-surface focus:outline-none focus:border-primary-container">${opts}</select></label>
    <div id="set-provider-fields" class="flex flex-col gap-space-xs"></div>
    <div class="flex items-center justify-between bg-surface-container-lowest p-space-sm rounded border border-outline-variant/20"><div class="flex flex-col"><span class="font-body-sm text-body-sm text-on-surface font-medium leading-tight">Injection guard</span><span class="font-badge-label text-badge-label leading-tight" id="set-guard-note">${s.guard_on ? "enforcing: flagged messages are blocked" : "off: flagged messages reach the model"}</span></div>
      <label class="relative inline-flex items-center cursor-pointer"><input class="sr-only peer" id="set-guard" type="checkbox" ${s.guard_on ? "checked" : ""}><div class="w-11 h-6 bg-surface-container-highest rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-on-surface after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-secondary"></div></label></div>
    <label class="flex flex-col gap-space-2xs"><div class="flex items-center justify-between"><span class="font-mono-data text-badge-label text-outline uppercase">Block threshold (demo override)</span><span class="font-mono-data text-badge-label text-on-surface" id="set-thr-value">${(s.threshold ?? st.threshold).toFixed(3)}</span></div><input id="set-threshold" type="range" min="-3" max="4" step="0.01" value="${s.threshold ?? st.threshold}" class="w-full"><span class="font-mono-data text-badge-label text-outline">the model's own threshold is ${st.threshold.toFixed(3)}; this moves only where the page blocks</span></label></div>`;
}
function bindSettings(st, s, onChange) {
  const fields = document.getElementById("set-provider-fields");
  const render = () => {
    const spec = st.providers.find(p => p.name === s.provider) || st.providers[0];
    if (spec.protocol === "stub") { fields.innerHTML = `<span class="font-mono-data text-badge-label text-outline">${esc(spec.note)}</span>`; return; }
    fields.innerHTML = `${spec.protocol !== "local" ? `<label class="flex flex-col gap-space-2xs"><span class="font-mono-data text-badge-label text-outline uppercase">Base URL</span><input id="set-url" class="bg-surface-container-lowest border border-outline-variant/40 rounded p-space-xs font-mono-data text-body-sm text-on-surface" value="${esc(s.base_url || spec.url)}"></label>` : ""}
      <label class="flex flex-col gap-space-2xs"><span class="font-mono-data text-badge-label text-outline uppercase">Model</span><input id="set-model" class="bg-surface-container-lowest border border-outline-variant/40 rounded p-space-xs font-mono-data text-body-sm text-on-surface" value="${esc(s.model || spec.model)}"></label>
      ${spec.key !== "none" ? `<label class="flex flex-col gap-space-2xs"><span class="font-mono-data text-badge-label text-outline uppercase">API key${spec.key === "optional" ? " (optional)" : ""}</span><input id="set-key" type="password" class="bg-surface-container-lowest border border-outline-variant/40 rounded p-space-xs font-mono-data text-body-sm text-on-surface" value="${esc(s.api_key || "")}" placeholder="sent with each request, never stored"></label>` : ""}
      ${spec.note ? `<span class="font-mono-data text-badge-label text-outline">${esc(spec.note)}</span>` : ""}`;
    fields.querySelectorAll("input").forEach(el => el.addEventListener("input", () => { s.base_url = (document.getElementById("set-url") || {}).value || ""; s.model = (document.getElementById("set-model") || {}).value || ""; s.api_key = (document.getElementById("set-key") || {}).value || ""; saveSettings(s); onChange && onChange(); }));
  };
  document.getElementById("set-provider").addEventListener("change", e => { s.provider = e.target.value; s.model = ""; s.base_url = ""; saveSettings(s); render(); onChange && onChange(); });
  document.getElementById("set-guard").addEventListener("change", e => { s.guard_on = e.target.checked; document.getElementById("set-guard-note").textContent = s.guard_on ? "enforcing: flagged messages are blocked" : "off: flagged messages reach the model"; saveSettings(s); onChange && onChange(); });
  document.getElementById("set-threshold").addEventListener("input", e => { s.threshold = Number(e.target.value); document.getElementById("set-thr-value").textContent = s.threshold.toFixed(3); saveSettings(s); onChange && onChange(); });
  render();
}
function requestBody(s, message, document_, surface) {
  return { message, document: document_ || "", guard_on: !!s.guard_on, threshold: s.threshold, provider: s.provider, model: s.model || null, base_url: s.base_url || null, api_key: s.api_key || null, session: SESSION, surface };
}
