// Shots on Goal web app. No build step: one module, hash routing, settings saved to your account.
const view = document.getElementById("view");

let ME = null;          // /api/me
let TEAMS = {};         // abbr -> {place, name, color, light}
let CHANGES = [];       // What's new entries, newest first (/api/changes)
let STANDINGS = {};     // per league: team names, records and divisions
// Which league the app shows: nhl | pwhl | both (Tonight and the Wire only; other pages pick one). Per device.
let LEAGUE = (() => { try { return localStorage.getItem("league") || "nhl"; } catch { return "nhl"; } })();
const LEAGUE_NAME = { nhl: "NHL", pwhl: "PWHL" };
// Standings and Teams always show one league; in Both mode they remember their own pick.
function pageLeague() {
  if (LEAGUE !== "both") return LEAGUE;
  try { return localStorage.getItem("pageLeague") || "nhl"; } catch { return "nhl"; }
}
function setLeague(l) {
  LEAGUE = l;
  try { localStorage.setItem("league", l); } catch { /* fine */ }
  applyLeague();
  route();
}
function applyLeague() {
  document.body.classList.toggle("league-pwhl", LEAGUE === "pwhl");
  document.querySelectorAll("[data-league]").forEach(b => b.classList.toggle("on", b.dataset.league === LEAGUE));
}
const leagueOf = abbr => (abbr || "").startsWith("PW-") ? "pwhl" : "nhl";
const gameHref = g => g.league === "pwhl" ? `#/pgame/${g.id}` : `#/game/${g.id}`;
let refreshTimer = null;
let INSTALL_PROMPT = null;  // Android/desktop Chrome hand us this so we can show a real Install button

window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); INSTALL_PROMPT = e; });
window.addEventListener("appinstalled", () => { INSTALL_PROMPT = null; });

const isStandalone = () => window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
function device() {
  const ua = navigator.userAgent;
  const ios = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (ios) return /CriOS|FxiOS|EdgiOS/.test(ua) ? "ios-other" : "ios";
  if (/Android/.test(ua)) return "android";
  return "desktop";
}
const SHARE_ICON = `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M8 7l4-4 4 4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M6 11H5v10h14V11h-1" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`;
const DOTS_ICON = `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="5" r="2" fill="currentColor"/><circle cx="12" cy="12" r="2" fill="currentColor"/><circle cx="12" cy="19" r="2" fill="currentColor"/></svg>`;

// ---- helpers ------------------------------------------------------------------
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Cloudflare's codes for "the Pi can't be reached" (a bug in the app is a plain 500): show the offline page.
const PI_DOWN = status => [502, 503, 504, 520, 521, 522, 523, 524, 530].includes(status);
const goOffline = () => location.replace(`/offline.html?back=${encodeURIComponent(location.href)}`);

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { Accept: "application/json", "Content-Type": "application/json" }, ...opts });
  if (PI_DOWN(r.status)) goOffline();
  if (!r.ok) {
    const err = new Error(`${path}: ${r.status}`);
    err.status = r.status;
    try { err.detail = (await r.json()).detail; } catch { /* not JSON */ }
    throw err;
  }
  return r.json();
}

const favs = () => new Set(ME?.settings?.favorites || []);

function mark(abbr, big = false) {
  const t = TEAMS[abbr] || {};
  return `<span class="mark${t.light ? " light" : ""}${big ? " big" : ""}" style="--c:${esc(t.color || "#666")}">${esc(t.code || abbr)}</span>`;
}

const teamName = abbr => TEAMS[abbr]?.name || abbr;
const fullName = abbr => TEAMS[abbr] ? `${TEAMS[abbr].place} ${TEAMS[abbr].name}` : abbr;

const time = iso => new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });

function dayTitle(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((date - today) / 86400000);
  const label = date.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
  if (diff === 0) return `Today · ${label}`;
  if (diff === 1) return `Tomorrow · ${label}`;
  if (diff === -1) return `Yesterday · ${label}`;
  return label;
}

const shortDate = iso => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }); };

function statusCell(g) {
  if (g.state === "live") {
    const where = g.intermission ? `${g.period} INT` : `${g.period} ${g.clock || ""}`;
    const sit = g.situation && !g.intermission ? `<div class="sit">${esc(g.situation.power_play ? `${g.situation.power_play} PP` : g.situation.away_pulled || g.situation.home_pulled ? "Empty net" : g.situation.text)}</div>` : "";
    return `<div class="status"><div class="live">LIVE</div><div class="t">${esc(where)}</div>${sit}</div>`;
  }
  if (g.state === "final") {
    const extra = g.outcome && g.outcome !== "REG" ? `/${g.outcome}` : "";
    return `<div class="status"><div class="t">Final${esc(extra)}</div></div>`;
  }
  if (g.state === "postponed") return `<div class="status"><div class="t">Postponed</div></div>`;
  return `<div class="status"><div class="t">${g.start ? esc(time(g.start)) : "TBD"}</div></div>`;
}

function watchLine(w, game) {
  if (!w || game.state === "final") return "";
  if (!w.network && !(w.links || []).length) return `<div class="watch"><span>${esc(w.why)}</span></div>`;
  const pill = w.have === true ? `<span class="pill have">You have it</span>`
    : w.have === false ? `<span class="pill need">Not in your services</span>` : "";
  const links = w.links || [];
  const app = links.length
    ? links.map(l => `<a class="app" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.name)} ↗</a>`).join(`<span>or</span>`)
    : `<span class="app">${esc(w.app)}</span>`;
  return `<div class="watch">${app}<span>${esc(w.why)}</span>${pill}</div>`;
}

function gameCard(g, fav) {
  const a = g.away, h = g.home, done = g.state === "final";
  const lost = side => done && a.score != null && h.score != null && side.score < (side === a ? h.score : a.score) ? " lost" : "";
  const sc = t => g.state === "pre" || g.state === "postponed" ? "" : `<span class="sc">${t.score ?? ""}</span>`;
  const isFav = fav.has(a.abbr) || fav.has(h.abbr);
  // The watch line sits outside the game link so its own link (ESPN+, NESN 360...) can be tapped.
  return `<div class="game${isFav ? " fav" : ""}">
    <a class="body" href="${gameHref(g)}">
      <div class="team-line${lost(a)}">${mark(a.abbr)}<span class="nm">${esc(a.name || teamName(a.abbr))}</span>${sc(a)}</div>
      ${statusCell(g)}
      <div class="team-line${lost(h)}">${mark(h.abbr)}<span class="nm">${esc(h.name || teamName(h.abbr))}</span>${sc(h)}</div>
    </a>
    ${watchLine(g.watch, g)}${ticketLink(g)}
  </div>`;
}

// Tickets only make sense before puck drop. NHL links go straight to the game on Ticketmaster.
const ticketLink = g => g.state === "pre" && g.tickets
  ? `<a class="tix" href="${esc(g.tickets)}" target="_blank" rel="noopener">Tickets ↗</a>` : "";

function setNav(name) {
  document.querySelectorAll("[data-nav]").forEach(a => a.classList.toggle("active", a.dataset.nav === name));
}

function autoRefresh(fn, seconds) {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => { if (!document.hidden) fn(true); else autoRefresh(fn, seconds); }, seconds * 1000);
}

const failed = e => `<div class="notice error">${esc(e.detail || "Couldn't load that. The NHL's data may be down; try again in a minute.")}</div>`;

async function standings(league = "nhl") {
  if (!STANDINGS[league]) STANDINGS[league] = await api(`/api/standings?league=${league}`);
  return STANDINGS[league];
}

function leaguePicker(current) {
  // Only shown in Both mode, on pages that always show one league.
  if (LEAGUE !== "both") return "";
  return `<div class="seg">${["nhl", "pwhl"].map(l => `<button data-page-league="${l}" class="${l === current ? "on" : ""}">${LEAGUE_NAME[l]}</button>`).join("")}</div>`;
}
function bindLeaguePicker(again) {
  view.querySelectorAll("[data-page-league]").forEach(b => b.addEventListener("click", () => {
    try { localStorage.setItem("pageLeague", b.dataset.pageLeague); } catch { /* fine */ }
    again();
  }));
}

// ---- What's new ---------------------------------------------------------------------
// Unseen = newer than the last entry this person opened the page at. Someone who has never opened it sees
// the last week's entries as new.
function unseenChanges() {
  const seen = ME?.settings?.seen_changes;
  const i = seen ? CHANGES.findIndex(c => c.id === seen) : -1;
  if (i >= 0) return CHANGES.slice(0, i);
  const week = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
  return CHANGES.filter(c => c.date >= week);
}

async function markChangesSeen() {
  if (!CHANGES.length || ME.settings?.seen_changes === CHANGES[0].id) return;
  ME.settings = await api("/api/settings", { method: "PUT", body: JSON.stringify({ ...ME.settings, seen_changes: CHANGES[0].id }) }).catch(() => ME.settings);
  updateNewDot();
}

function updateNewDot() {
  document.querySelector(".top-link")?.classList.toggle("has-new", unseenChanges().length > 0);
}

function newBanner() {
  const fresh = unseenChanges();
  if (!fresh.length) return "";
  const lead = fresh.find(c => c.link !== "#/new") || fresh[0];  // headline a feature, not this page itself
  const more = fresh.length > 1 ? ` and ${fresh.length - 1} more` : "";
  return `<div class="newbar"><span class="pill info">New</span><span><b>${esc(lead.title)}</b>${more}</span>
    <a class="btn small" href="#/new">See what's new</a><button class="x" id="newbar-x" aria-label="Dismiss">×</button></div>`;
}

function bindNewBanner() {
  document.getElementById("newbar-x")?.addEventListener("click", async e => {
    e.target.closest(".newbar")?.remove();
    await markChangesSeen();
  });
}

const KIND_NAME = { new: "New", improved: "Improved", fixed: "Fixed" };

function whatsNewView() {
  setNav("settings");
  const fresh = new Set(unseenChanges().map(c => c.id));
  const days = CHANGES.reduce((m, c) => ((m[c.date] ||= []).push(c), m), {});
  view.innerHTML = `<h1>What's new</h1>
    <p class="muted">Every update to Shots on Goal, newest first.</p>
    ${Object.entries(days).map(([d, list]) => `<h2>${esc(new Date(d + "T12:00").toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" }))}</h2>
      <div class="card">${list.map(c => `<div class="change${fresh.has(c.id) ? " fresh" : ""}">
        <div class="change-head"><span class="pill ${c.kind === "new" ? "have" : "info"}">${esc(KIND_NAME[c.kind] || c.kind)}</span>
          <b>${esc(c.title)}</b>${fresh.has(c.id) ? `<span class="dot" aria-label="unread"></span>` : ""}</div>
        <div class="change-text">${esc(c.text)}</div>
        ${c.link && c.link !== "#/new" ? `<a class="change-link" href="${esc(c.link)}">Try it →</a>` : ""}</div>`).join("")}</div>`).join("")}
    <p class="muted small source-note">Shots on Goal is free software (AGPL-3.0). <a href="${esc(document.querySelector('meta[name="source"]')?.content || "")}" target="_blank" rel="noopener">Source code ↗</a></p>`;
  markChangesSeen();
}

// ---- gate -------------------------------------------------------------------------
function gateView() {
  document.getElementById("tabs").hidden = true;
  const s = ME.status;
  let body;
  if (s === "signed-out") {
    body = `<h1>Signed out</h1><p class="muted">Reload the page to sign in.</p>`;
  } else if (s === "pending") {
    body = `<h1>Request sent</h1>
      <p class="muted">You're on the list as <b>${esc(ME.email)}</b>. Once you're approved, just reload this page.</p>
      <button class="btn" id="reload">Reload</button>`;
  } else if (s === "denied" || s === "revoked") {
    body = `<h1>No access</h1><p class="muted">${esc(ME.email)} doesn't have access to Shots on Goal.</p>`;
  } else {
    body = `<h1>Shots on Goal</h1>
      <p class="muted">NHL scores, standings and where to watch, for a few friends.</p>
      <p>You're signed in as <b>${esc(ME.email)}</b>.</p>
      <button class="btn primary" id="ask">Request access</button>`;
  }
  view.innerHTML = `<div class="gate"><div class="card">${body}</div></div>`;
  document.getElementById("reload")?.addEventListener("click", () => location.reload());
  document.getElementById("ask")?.addEventListener("click", async e => {
    e.target.disabled = true;
    try {
      const r = await api("/api/request", { method: "POST" });
      ME.status = r.status;
    } catch { ME.status = "pending"; }
    gateView();
  });
}

// ---- Tonight ----------------------------------------------------------------------
// ---- "your team" cards ------------------------------------------------------------------------
// The top of Tonight: one card per favourite (swipe between them), tinted in the team's colour. /api/myteams is
// built from cached schedules and standings; kept for 5 minutes here so the 15-second refresh doesn't re-ask.
let myTeams = { at: 0, data: null };
async function loadMyTeams() {
  if (!favs().size) return null;
  if (myTeams.data && Date.now() - myTeams.at < 5 * 60000) return myTeams.data;
  try { myTeams = { at: Date.now(), data: await api("/api/myteams") }; } catch { /* the card is extra: skip it */ }
  return myTeams.data;
}

const RESULT_WORD = { W: "W", L: "L", OT: "OTL" };
const STREAK_WORD = { W: "won", L: "lost", OT: "lost in OT" };
function streakText(code) {
  const m = /^(W|L|OT)(\d+)$/.exec(code || "");
  if (!m || m[2] === "1") return "";
  return m[1] === "OT" ? `${m[2]} OT losses in a row` : `${STREAK_WORD[m[1]][0].toUpperCase()}${STREAK_WORD[m[1]].slice(1)} ${m[2]} straight`;
}

function heroCard(c, live) {
  const g = live || c.next;
  const t = TEAMS[c.abbr] || {};
  const side = g && (g.home.abbr === c.abbr ? { us: g.home, them: g.away, at: "vs" } : { us: g.away, them: g.home, at: "at" });
  let kicker = "No games scheduled", right = "";
  if (g) {
    const today = g.date === myTeams.data?.date;
    if (g.state === "live") {
      kicker = "Live now";
      right = `<b class="hero-sc">${side.us.score ?? 0}–${side.them.score ?? 0}</b><span>${esc(g.intermission ? `${g.period} INT` : `${g.period} ${g.clock || ""}`)}</span>`;
    } else if (g.state === "final") {
      const won = side.us.score > side.them.score;
      kicker = "Final tonight";
      right = `<b class="hero-sc">${won ? "W" : g.outcome && g.outcome !== "REG" ? "OTL" : "L"} ${side.us.score}–${side.them.score}</b>${g.outcome && g.outcome !== "REG" ? `<span>${esc(g.outcome)}</span>` : ""}`;
    } else {
      kicker = today ? "Tonight" : `Next game · ${shortDate(g.date)}`;
      right = `<b class="hero-sc">${g.start ? esc(time(g.start)) : "TBD"}</b>`;
    }
  }
  const w = g && g.state !== "final" ? g.watch : null;
  const watch = w && (w.network || w.app) ? `<span class="chip strong">${esc(w.network || w.app)}${w.have === true ? " · you have it" : w.have === false ? " · not in your services" : ""}</span>` : "";
  const st = c.standing;
  const chips = [watch,
    st?.place ? `<span class="chip">${esc(st.place)}</span>` : "",
    c.record ? `<span class="chip">${esc(c.record)}${st?.pts != null ? ` · ${st.pts} pts` : ""}</span>` : "",
    streakText(c.streak) ? `<span class="chip">${esc(streakText(c.streak))}</span>` : "",
    st?.race ? `<span class="chip">${esc(st.race)}</span>` : ""].join("");
  const lastIsThis = c.last && g && c.last.id === g.id;
  const lines = [
    c.week && c.week.games ? `<div><b>Last 7 days</b> ${esc(c.week.record)} · ${c.week.gf} goals for, ${c.week.ga} against</div>` : "",
    c.last && !lastIsThis ? `<div><b>Last</b> ${RESULT_WORD[c.last.code]} ${c.last.us}–${c.last.them} ${c.last.home ? "vs" : "at"} ${esc(teamName(c.last.opp))}</div>` : "",
    c.after?.length ? `<div><b>Then</b> ${c.after.map(a => `${a.home ? "vs" : "at"} ${esc(TEAMS[a.opp]?.code || a.opp)} ${esc(shortDate(a.date).split(",")[0])}`).join(" · ")}</div>` : "",
  ].join("");
  return `<div class="hero${t.light ? " light" : ""}" style="--c:${esc(t.color || "#333")}">
    <a class="hero-top" href="${g ? gameHref(g) : `#/team/${encodeURIComponent(c.abbr)}`}">
      <div class="hero-k">${esc(teamName(c.abbr))} · ${esc(kicker)}</div>
      <div class="hero-m">${mark(c.abbr)}${side ? `<span>${side.at}</span>${mark(side.them.abbr)}<span class="hero-opp">${esc(teamName(side.them.abbr))}</span>` : ""}
        <span class="hero-r">${right}</span></div>
    </a>
    ${chips ? `<div class="hero-chips">${chips}</div>` : ""}
    ${lines ? `<div class="hero-lines">${lines}</div>` : ""}
  </div>`;
}

function heroes(data, leagues, slateGames) {
  if (!data?.teams?.length) return "";
  // Playing now first, then today's games in favourites order, then everyone else by their next game.
  const order = ME.settings.favorites;
  const rank = c => { const g = slateGames.find(x => x.away.abbr === c.abbr || x.home.abbr === c.abbr);
    return g ? [0, g.state === "live" ? 0 : 1, String(order.indexOf(c.abbr)).padStart(3, "0")] : [1, 0, c.next?.start || c.next?.date || "9"]; };
  const cards = data.teams.filter(c => leagues.includes(c.league))
    .sort((x, y) => { const a = rank(x), b = rank(y); return a[0] - b[0] || a[1] - b[1] || String(a[2]).localeCompare(String(b[2])); });
  if (!cards.length) return "";
  const live = c => slateGames.find(x => x.away.abbr === c.abbr || x.home.abbr === c.abbr);
  return `<div class="heroes${cards.length > 1 ? " many" : ""}">${cards.map(c => heroCard(c, live(c))).join("")}</div>`;
}

async function tonightView(date, quiet = false) {
  setNav("tonight");
  if (!quiet) view.innerHTML = `<div class="empty">Loading games…</div>`;
  const leagues = LEAGUE === "both" ? ["nhl", "pwhl"] : [LEAGUE];
  let days, mineData = null;
  try {
    // Both leagues: the NHL's date leads, so the PWHL slate is for the same day.
    const mine = date ? null : loadMyTeams();
    const first = await api(`/api/games?league=${leagues[0]}${date ? `&date=${encodeURIComponent(date)}` : ""}`);
    days = [first];
    if (leagues[1]) days.push(await api(`/api/games?league=${leagues[1]}&date=${encodeURIComponent(date || first.date)}`));
    mineData = await mine;
  } catch (e) {
    view.innerHTML = failed(e);
    return;
  }
  const fav = favs();
  const order = g => ({ live: 0, pre: 1, postponed: 2, final: 3 }[g.state] ?? 1);
  const section = (title, list) => list.length ? `<h2>${title}</h2><div class="card">${list.map(g => gameCard(g, fav)).join("")}</div>` : "";
  const slate = (day, league) => {
    const games = day.games || [];
    const mine = games.filter(g => fav.has(g.away.abbr) || fav.has(g.home.abbr));
    const rest = games.filter(g => !mine.includes(g));
    rest.sort((x, y) => order(x) - order(y) || (x.start || "").localeCompare(y.start || ""));
    const head = leagues.length > 1 ? `<div class="league-head ${league}">${LEAGUE_NAME[league]}</div>` : "";
    if (!games.length) return head + `<div class="empty">No ${LEAGUE_NAME[league]} games this day.</div>`;
    return head + section("Your teams", mine) + section(mine.length ? "Around the league" : "All games", rest);
  };
  const dates = days.map(d => d.date).filter(Boolean);
  const day = { date: days[0].date || dates[0],
    // Arrows step to the nearest day with a game in any shown league.
    prev: days.map(d => d.prev).filter(Boolean).sort().pop(), next: days.map(d => d.next).filter(Boolean).sort()[0] };
  view.innerHTML = `
    ${newBanner()}
    <div id="getapp"></div>
    ${heroes(mineData, leagues, days.flatMap(d => d.games || []))}
    <div class="daybar">
      ${day.prev ? `<a href="#/day/${day.prev}" aria-label="Previous day">←</a>` : "<span></span>"}
      <h1>${esc(day.date ? dayTitle(day.date) : "Games")}</h1>
      ${day.next ? `<a href="#/day/${day.next}" aria-label="Next day">→</a>` : "<span></span>"}
    </div>
    ${days.map((d, i) => slate(d, leagues[i])).join("")}`;
  getAppBanner();
  bindNewBanner();
  const all = days.flatMap(d => d.games || []);
  if (all.some(g => g.state === "live" || (g.state === "pre" && Date.parse(g.start) - Date.now() < 30 * 60000))) {
    autoRefresh(q => tonightView(date, q), 15);
  }
}

// ---- getting the app + alerts --------------------------------------------------------------
async function getAppBanner() {
  const box = document.getElementById("getapp");
  if (!box) return;
  let hidden = false;
  try { hidden = localStorage.getItem("getappHidden") === "1"; } catch { /* fine */ }
  if (hidden) return;
  let text = null;
  if (!isStandalone() && device() !== "desktop") {
    text = "<b>Put Shots on Goal on your home screen</b> and get alerts when your teams score.";
  } else if ("PushManager" in window && Notification.permission === "default") {
    const reg = await navigator.serviceWorker?.ready.catch(() => null);
    const sub = reg ? await reg.pushManager.getSubscription().catch(() => null) : null;
    if (!sub) text = "<b>Turn on alerts</b> for puck drop, goals and finals for your teams.";
  }
  if (!text) return;
  box.innerHTML = `<div class="getapp"><div>${text}</div><a class="btn primary small" href="#/app">Show me how</a>
    <button class="x" aria-label="Hide">×</button></div>`;
  box.querySelector(".x").addEventListener("click", () => {
    try { localStorage.setItem("getappHidden", "1"); } catch { /* fine */ }
    box.innerHTML = "";
  });
}

function appView() {
  setNav("settings");
  const d = device(), standalone = isStandalone();
  let step1;
  if (standalone) {
    step1 = `<p class="done">✓ You're using the home-screen app.</p>`;
  } else if (d === "ios") {
    step1 = `<ol class="steps">
      <li>Tap the <b>Share</b> button ${SHARE_ICON} at the bottom of Safari (top right on iPad).</li>
      <li>Scroll down and tap <b>Add to Home Screen</b>.</li>
      <li>Tap <b>Add</b>, then open <b>Shots on Goal</b> from your home screen and come back to this page (Settings → How to get the app).</li></ol>`;
  } else if (d === "ios-other") {
    step1 = `<p>On iPhone this works best from <b>Safari</b>. Copy this page's address, open it in Safari, then follow the steps there.</p>
      <div class="copyrow" style="padding:0"><input class="field" readonly value="${esc(location.origin)}/#/app"><button class="btn" id="copyapp">Copy</button></div>`;
  } else if (INSTALL_PROMPT) {
    step1 = `<p>One tap:</p><button class="btn primary" id="install">Install Shots on Goal</button>`;
  } else if (d === "android") {
    step1 = `<ol class="steps">
      <li>In Chrome, tap the menu ${DOTS_ICON} at the top right.</li>
      <li>Tap <b>Add to Home screen</b> (or <b>Install app</b>), then <b>Install</b>.</li>
      <li>Open <b>Shots on Goal</b> from your home screen.</li></ol>`;
  } else {
    step1 = `<p>On a computer this is optional; alerts work in the browser too. In Chrome or Edge, click the install icon at the right end of the address bar, or the menu ${DOTS_ICON} → <b>Install Shots on Goal</b>.</p>`;
  }
  view.innerHTML = `
    <h1>Get the app</h1>
    <p class="muted">Shots on Goal works like an app once it's on your home screen: its own icon, full screen, and alerts for your teams.</p>
    <h2>1. Add it to your home screen</h2>
    <div class="card pad">${step1}</div>
    <h2>2. Turn on alerts</h2>
    <div class="card" id="notif"><div class="empty">Checking this device…</div></div>
    <p class="help">You'll get puck drop, goals and finals for your favorite teams, plus trades. Pick which in <a href="#/settings">Settings</a>${ME.settings.favorites.length ? "" : " (and choose your favorite teams there first)"}.</p>`;
  showNotifications();
  document.getElementById("install")?.addEventListener("click", async () => {
    INSTALL_PROMPT.prompt();
    await INSTALL_PROMPT.userChoice.catch(() => null);
    INSTALL_PROMPT = null;
    appView();
  });
  document.getElementById("copyapp")?.addEventListener("click", async e => {
    try { await navigator.clipboard.writeText(`${location.origin}/#/app`); e.target.textContent = "Copied"; } catch { /* the field is selectable */ }
  });
}

// ---- Game ---------------------------------------------------------------------------
function compareRow(label, a, h, ac, hc) {
  const num = v => typeof v === "number" ? v : parseFloat(String(v).split("/")[0]) || 0;
  const na = num(a), nh = num(h), total = na + nh || 1;
  return `<div class="cmp"><span class="v">${esc(a)}</span>
    <div><div class="lbl">${esc(label)}</div><div class="bar"><i style="width:${na / total * 100}%;background:${ac}"></i><i style="width:${nh / total * 100}%;background:${hc}"></i></div></div>
    <span class="v">${esc(h)}</span></div>`;
}

async function gameView(id, quiet = false, league = "nhl") {
  setNav("tonight");
  if (!quiet) view.innerHTML = `<div class="empty">Loading game…</div>`;
  let d;
  const path = league === "pwhl" ? `/api/pwhl/game/${encodeURIComponent(id)}` : `/api/game/${encodeURIComponent(id)}`;
  try { d = await api(path); } catch (e) { view.innerHTML = failed(e); return; }
  const g = d.game, a = g.away.abbr, h = g.home.abbr;
  const ac = TEAMS[a]?.color || "#888", hc = TEAMS[h]?.color || "#888";
  let state = "";
  if (g.state === "live") state = `<span class="live">LIVE</span> ${esc(g.intermission ? `${g.period} intermission` : `${g.period} · ${g.clock || ""}`)}`;
  else if (g.state === "final") state = `Final${g.outcome && g.outcome !== "REG" ? ` (${esc(g.outcome)})` : ""}`;
  else if (g.state === "postponed") state = "Postponed";
  else state = g.start ? `${esc(shortDate(g.date))} · ${esc(time(g.start))}` : "Time TBD";
  const showScore = g.state === "live" || g.state === "final";
  const side = (t, abbr) => `<a class="side" href="#/team/${abbr}">${mark(abbr, true)}<span class="nm">${esc(t.name || teamName(abbr))}</span></a>`;

  let html = `<div class="card" style="margin-top:12px">
    <div class="scorebug">
      ${side(g.away, a)}
      <div><div class="score">${showScore ? `${g.away.score ?? 0} – ${g.home.score ?? 0}` : "vs"}</div><div class="state">${state}</div></div>
      ${side(g.home, h)}
    </div>
    ${g.state !== "final" ? `<div style="padding:0 14px 14px">${watchLine(g.watch, g)}</div>` : ""}
    ${g.state !== "final" && g.watch?.links?.length ? `<div class="links">${g.watch.links.map((l, i) =>
      `<a class="btn${i ? "" : " primary"}" href="${esc(l.url)}" target="_blank" rel="noopener">Open ${esc(l.name)}</a>`).join("")}</div>` : ""}
    ${g.recap ? `<div class="links"><a class="btn" href="${esc(g.recap)}" target="_blank" rel="noopener">Watch the recap on NHL.com</a></div>` : ""}
    ${g.state === "pre" && g.tickets ? `<div class="links"><a class="btn" href="${esc(g.tickets)}" target="_blank" rel="noopener">Buy tickets ↗</a></div>` : ""}
    ${g.state !== "final" && league !== "pwhl" ? `<div class="links"><button class="linkish" id="report">Wrong channel? Tell us</button></div>` : ""}
  </div>
  ${d.situation && g.state === "live" && !g.intermission ? `<div class="banner">${esc(d.situation.text)}</div>` : ""}
  ${d.recap ? `<p class="recap">${esc(d.recap)}</p>` : ""}`;

  if (d.linescore.length) {
    const shots = Object.fromEntries(d.shots.map(s => [s.period, s]));
    html += `<h2>By period</h2><div class="card scroll"><table>
      <tr><th></th>${d.linescore.map(p => `<th>${esc(p.period)}</th>`).join("")}<th>T</th><th>SOG</th></tr>
      ${["away", "home"].map(s => `<tr><td class="team"><span class="tm">${mark(s === "away" ? a : h)}</span></td>
        ${d.linescore.map(p => `<td>${p[s] ?? ""}<span class="muted small">${shots[p.period] ? ` · ${shots[p.period][s]}` : ""}</span></td>`).join("")}
        <td><b>${g[s].score ?? 0}</b></td><td>${g[s].sog ?? ""}</td></tr>`).join("")}
    </table></div><p class="help">Goals · shots in each period.</p>`;
  }

  const goals = d.scoring.filter(p => p.goals.length);
  if (goals.length) {
    html += `<h2>Scoring</h2><div class="card">${goals.map(p => `<div class="subhead">${esc(p.period)}</div>${p.goals.map(x => {
      const tags = [x.strength !== "EV" ? x.strength : "", x.modifier === "empty-net" ? "EN" : ""].filter(Boolean)
        .map(t => `<span class="tag">${esc(t)}</span>`).join("");
      const assists = x.assists.length ? x.assists.map(y => `${esc(y.name)}${y.total ? ` (${y.total})` : ""}`).join(", ") : "Unassisted";
      return `<div class="event"><span class="when">${esc(x.time)}</span>${mark(x.team)}
        <div><span class="run">${x.away}–${x.home}</span><div class="who">${esc(x.scorer)}${x.total ? ` (${x.total})` : ""}${tags}</div>
        <div class="detail">${assists}${x.clip ? ` · <a href="${esc(x.clip)}" target="_blank" rel="noopener">clip</a>` : ""}</div></div></div>`;
    }).join("")}`).join("")}</div>`;
  }

  if (d.shotmap?.length) html += shotMap(d.shotmap, a, h);

  if (d.stars.length) {
    html += `<h2>Three stars</h2><div class="card">${d.stars.map(s => `<div class="event"><span class="when">${"★".repeat(s.star)}</span>${mark(s.team)}
      <div><div class="who">${esc(s.name)} <span class="muted small">${esc(s.pos)}</span></div><div class="detail">${esc(s.line)}</div></div></div>`).join("")}</div>`;
  }

  if (d.team_stats.length) {
    html += `<h2>Team stats</h2><div class="card compare">
      <div class="cmp"><span>${mark(a)}</span><span></span><span style="text-align:right">${mark(h)}</span></div>
      ${d.team_stats.map(s => compareRow(s.label, s.away, s.home, ac, hc)).join("")}</div>`;
  }

  const pens = d.penalties.filter(p => p.items.length);
  if (pens.length) {
    html += `<h2>Penalties</h2><div class="card">${pens.map(p => `<div class="subhead">${esc(p.period)}</div>${p.items.map(x =>
      `<div class="event"><span class="when">${esc(x.time)}</span>${mark(x.team)}<div><div class="who">${esc(x.player || "Bench")}</div>
      <div class="detail">${esc(x.desc)} · ${x.minutes} min</div></div></div>`).join("")}`).join("")}</div>`;
  }

  for (const s of ["away", "home"]) {
    const p = d.players[s];
    if (!p || !p.skaters.length) continue;
    const abbr = s === "away" ? a : h;
    html += `<h2>${esc(teamName(abbr))} players</h2><div class="card scroll"><table>
      <tr><th>Skater</th><th>G</th><th>A</th><th>P</th><th>+/-</th><th>SOG</th><th>Hits</th><th>TOI</th></tr>
      ${p.skaters.map(x => `<tr><td>${esc(x.name)} <span class="muted small">${esc(x.pos)}</span></td><td>${x.g}</td><td>${x.a}</td><td><b>${x.p}</b></td><td>${x.pm > 0 ? "+" : ""}${x.pm}</td><td>${x.sog}</td><td>${x.hits}</td><td>${esc(x.toi || "")}</td></tr>`).join("")}
    </table>${p.goalies.length ? `<table><tr><th>Goalie</th><th>Saves</th><th>GA</th><th>SV%</th><th>TOI</th></tr>
      ${p.goalies.map(x => `<tr><td>${esc(x.name)}</td><td>${x.saves}/${x.sa}</td><td>${x.ga}</td><td>${x.sa ? (x.saves / x.sa).toFixed(3).replace(/^0/, "") : "–"}</td><td>${esc(x.toi || "")}</td></tr>`).join("")}</table>` : ""}</div>`;
  }

  if (g.venue) html += `<p class="help" style="text-align:center;margin-top:18px">${esc(g.venue)}</p>`;
  view.innerHTML = html;
  document.getElementById("report")?.addEventListener("click", async e => {
    const note = prompt(`We said: ${g.watch?.app || "no channel"} (${g.watch?.why || ""}).\nWhere is it actually on? (optional)`);
    if (note === null) return;
    e.target.disabled = true;
    try { await api("/api/report", { method: "POST", body: JSON.stringify({ game_id: g.id, note }) }); e.target.textContent = "Thanks, reported."; }
    catch { e.target.textContent = "Couldn't send that. Try again."; e.target.disabled = false; }
  });
  view.querySelectorAll("[data-shots]").forEach(b => b.addEventListener("click", () => {
    view.querySelectorAll("[data-shots]").forEach(x => x.classList.toggle("on", x === b));
    view.querySelectorAll(".rink [data-p]").forEach(dot => { dot.style.display = b.dataset.shots === "all" || dot.dataset.p === b.dataset.shots ? "" : "none"; });
  }));
  if (g.state === "live" || (g.state === "pre" && Date.parse(g.start) - Date.now() < 30 * 60000)) autoRefresh(q => gameView(id, q, league), 15);
}

// ---- Wire ----------------------------------------------------------------------------
const WIRE_KINDS = [["", "All"], ["move", "Moves"], ["news", "News"], ["insider", "Insiders"]];

function linkify(text) {
  return esc(text).replace(/https?:\/\/[^\s<]+/g, u => `<a href="${u}" target="_blank" rel="noopener">${u.replace(/^https?:\/\//, "").slice(0, 40)}…</a>`);
}

function wireItem(i, fav) {
  const isFav = i.teams.some(t => fav.has(t));
  const marks = i.teams.slice(0, 4).map(t => mark(t)).join("");
  const kind = i.kind === "move" ? (i.trade ? `<span class="pill need">Trade</span>` : `<span class="pill info">Move</span>`)
    : i.kind === "insider" ? `<span class="pill info">Insider</span>` : "";
  const head = `<div class="wmeta">${kind}<span class="src">${esc(i.source)}</span><span>${esc(ago(i.time))}</span><span class="wmarks">${marks}</span></div>`;
  let body;
  if (i.kind === "news") {
    body = `<a class="wtitle" href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a>${i.text ? `<div class="wtext">${esc(i.text)}</div>` : ""}`;
  } else if (i.kind === "insider") {
    body = `<div class="wtext full">${linkify(i.text)}</div>${i.link ? `<a class="wlink" href="${esc(i.link.url)}" target="_blank" rel="noopener">${esc(i.link.title || i.link.url)}</a>` : ""}
      <a class="wsub" href="${esc(i.url)}" target="_blank" rel="noopener">View on Bluesky ↗</a>`;
  } else {
    body = `<div class="wtext full">${esc(i.text)}</div>`;
  }
  return `<div class="witem${isFav ? " fav" : ""}">${head}${body}</div>`;
}

async function wireView(quiet = false) {
  setNav("wire");
  let state = { kind: "", mine: false };
  try { state = { ...state, ...JSON.parse(localStorage.getItem("wire") || "{}") }; } catch { /* defaults */ }
  if (!quiet) view.innerHTML = `<div class="empty">Loading the Wire…</div>`;
  const leagues = LEAGUE === "both" ? ["nhl", "pwhl"] : [LEAGUE];
  let lists;
  try {
    lists = await Promise.all(leagues.map(l => api(`/api/wire?league=${l}&kind=${state.kind}&mine=${state.mine ? 1 : 0}`)));
  } catch (e) { view.innerHTML = failed(e); return; }
  const fav = favs();
  const block = (items, l) => (leagues.length > 1 ? `<div class="league-head ${l}">${LEAGUE_NAME[l]}</div>` : "") +
    (items.length ? `<div class="card">${items.slice(0, leagues.length > 1 ? 40 : 150).map(i => wireItem(i, fav)).join("")}</div>`
      : `<div class="empty">Nothing here yet.${state.mine ? " Try turning off \"Only my teams\"." : ""}</div>`);
  view.innerHTML = `
    <div class="seg">${WIRE_KINDS.map(([k, l]) => `<button data-kind="${k}" class="${k === state.kind ? "on" : ""}">${l}</button>`).join("")}</div>
    <label class="toggle"><input type="checkbox" id="mine" ${state.mine ? "checked" : ""}> Only my teams</label>
    ${lists.map((items, i) => block(items, leagues[i])).join("")}
    <p class="help">${LEAGUE !== "pwhl" ? `NHL: moves from ESPN, headlines from ESPN and Sportsnet, insiders from Bluesky ("(mirror)" accounts repost an insider's posts from X). ` : ""}${LEAGUE !== "nhl" ? "PWHL: The Hockey News, The Ice Garden, and the league, teams and outlets on Bluesky." : ""}</p>`;
  const save = next => { try { localStorage.setItem("wire", JSON.stringify(next)); } catch { /* fine */ } wireView(); };
  view.querySelectorAll("[data-kind]").forEach(b => b.addEventListener("click", () => save({ ...state, kind: b.dataset.kind })));
  document.getElementById("mine").addEventListener("change", e => save({ ...state, mine: e.target.checked }));
  autoRefresh(q => wireView(q), 120);
}

// ---- shot map -----------------------------------------------------------------------------
// NHL rink coordinates: x -100..100 (end boards), y -42.5..42.5. Home shoots right, away shoots left.
function shotMap(shots, a, h) {
  const color = t => TEAMS[t]?.color || "#888";
  const periods = [...new Set(shots.map(s => s.period))];
  const count = (t, k) => shots.filter(s => s.team === t && (k ? s.kind === k : s.kind !== "miss")).length;
  const dot = s => {
    const c = color(s.team), cx = s.x.toFixed(1), cy = (-s.y).toFixed(1);
    const title = `<title>${esc(s.shooter)} · ${esc(s.period)} ${esc(s.time)} · ${esc(s.kind === "miss" ? "missed" : s.kind)}${s.shot_type ? ` (${esc(s.shot_type)})` : ""}</title>`;
    if (s.kind === "goal") return `<g data-p="${esc(s.period)}"><circle cx="${cx}" cy="${cy}" r="3.4" fill="${c}" stroke="var(--text)" stroke-width="1"/>${title}</g>`;
    if (s.kind === "miss") return `<circle data-p="${esc(s.period)}" cx="${cx}" cy="${cy}" r="1.6" fill="none" stroke="${c}" stroke-width=".7" opacity=".8">${title}</circle>`;
    return `<circle data-p="${esc(s.period)}" cx="${cx}" cy="${cy}" r="1.8" fill="${c}" opacity=".9">${title}</circle>`;
  };
  const line = "var(--border)";
  return `<h2>Shot map</h2><div class="card pad">
    <div class="shotlegend"><span>${mark(a)} shoots ←</span><span class="muted small">● shot · ○ miss · ◉ goal</span><span>→ ${mark(h)}</span></div>
    <svg class="rink" viewBox="-101 -44 202 88" role="img" aria-label="Shot map">
      <rect x="-100" y="-42.5" width="200" height="85" rx="28" fill="none" stroke="var(--muted)" stroke-width=".8"/>
      <line x1="0" y1="-42.5" x2="0" y2="42.5" stroke="var(--accent)" stroke-opacity=".5" stroke-width="1"/>
      <line x1="-25" y1="-42.5" x2="-25" y2="42.5" stroke="#3b6fd8" stroke-opacity=".5" stroke-width="1"/>
      <line x1="25" y1="-42.5" x2="25" y2="42.5" stroke="#3b6fd8" stroke-opacity=".5" stroke-width="1"/>
      <line x1="-89" y1="-37" x2="-89" y2="37" stroke="var(--accent)" stroke-opacity=".4" stroke-width=".5"/>
      <line x1="89" y1="-37" x2="89" y2="37" stroke="var(--accent)" stroke-opacity=".4" stroke-width=".5"/>
      <circle cx="0" cy="0" r="15" fill="none" stroke="${line}" stroke-width=".6"/>
      ${[[-69, -22], [-69, 22], [69, -22], [69, 22]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="15" fill="none" stroke="${line}" stroke-width=".6"/>`).join("")}
      <rect x="-93" y="-3" width="4" height="6" fill="none" stroke="var(--muted)" stroke-width=".6"/>
      <rect x="89" y="-3" width="4" height="6" fill="none" stroke="var(--muted)" stroke-width=".6"/>
      ${shots.filter(s => s.kind === "miss").map(dot).join("")}
      ${shots.filter(s => s.kind === "shot").map(dot).join("")}
      ${shots.filter(s => s.kind === "goal").map(dot).join("")}
    </svg>
    <div class="shotlegend small"><span>${count(a)} on goal · ${count(a, "miss")} missed</span><span>${count(h)} on goal · ${count(h, "miss")} missed</span></div>
    ${periods.length > 1 ? `<div class="seg" style="margin:10px 0 0">${["all", ...periods].map(p => `<button data-shots="${esc(p)}" class="${p === "all" ? "on" : ""}">${p === "all" ? "All" : esc(p)}</button>`).join("")}</div>` : ""}
  </div>`;
}

// ---- Standings -----------------------------------------------------------------------
const STANDING_MODES = [["division", "Division"], ["wildcard", "Wild card"], ["conference", "Conference"], ["league", "League"]];

function standingsTable(rows, opts = {}) {
  const fav = favs();
  return `<div class="card scroll"><table>
    <tr><th colspan="2">Team</th><th>GP</th><th>W</th><th>L</th><th>OT</th><th>PTS</th><th class="wide">RW</th><th>GD</th><th class="wide">L10</th><th>STRK</th></tr>
    ${rows.map((r, i) => `<tr class="${fav.has(r.abbr) ? "fav" : ""}${opts.cutAfter === i ? " cut" : ""}">
      <td class="rank">${opts.rank ? opts.rank(r, i) : i + 1}</td>
      <td class="team"><span class="tm">${mark(r.abbr)}<a href="#/team/${r.abbr}">${esc(r.short || r.abbr)}</a></span></td>
      <td>${r.gp}</td><td>${r.w}</td><td>${r.l}</td><td>${r.otl}</td><td><b>${r.pts}</b></td><td class="wide">${r.rw}</td>
      <td>${r.gd > 0 ? "+" : ""}${r.gd}</td><td class="wide">${esc(r.l10)}</td><td>${esc(r.streak)}</td></tr>`).join("")}
  </table></div>`;
}

function pwhlStandings(rows) {
  const fav = favs();
  const season = rows[0]?.season ? `<p class="help">${esc(rows[0].season)}${rows.every(r => !r.gp) ? " (not started yet)" : ""}. Points: regulation win 3, overtime or shootout win 2, overtime or shootout loss 1.</p>` : "";
  return `<div class="card scroll"><table>
    <tr><th colspan="2">Team</th><th>GP</th><th>W</th><th>OTW</th><th>OTL</th><th>L</th><th>PTS</th><th>GD</th><th class="wide">L10</th></tr>
    ${rows.map((r, i) => `<tr class="${fav.has(r.abbr) ? "fav" : ""}">
      <td class="rank">${r.clinched ? esc(r.clinched) : i + 1}</td>
      <td class="team"><span class="tm">${mark(r.abbr)}<a href="#/team/${r.abbr}">${esc(r.short || r.code)}</a></span></td>
      <td>${r.gp}</td><td>${r.w}</td><td>${r.otw}</td><td>${r.otl}</td><td>${r.l}</td><td><b>${r.pts}</b></td>
      <td>${r.gd > 0 ? "+" : ""}${r.gd}</td><td class="wide">${esc(r.l10)}</td></tr>`).join("")}
  </table></div>${season}`;
}

async function standingsView(mode = "division") {
  setNav("standings");
  view.innerHTML = `<div class="empty">Loading standings…</div>`;
  const lg = pageLeague();
  if (lg === "pwhl") {
    let rows;
    try { rows = await standings("pwhl"); } catch (e) { view.innerHTML = failed(e); return; }
    view.innerHTML = leaguePicker("pwhl") + pwhlStandings(rows);
    bindLeaguePicker(() => standingsView(mode));
    return;
  }
  let rows;
  try { rows = await standings(); } catch (e) { view.innerHTML = failed(e); return; }
  const by = (key, list) => list.reduce((m, r) => ((m[r[key]] ||= []).push(r), m), {});
  let body = "";
  if (mode === "league") {
    body = standingsTable([...rows].sort((x, y) => x.league_rank - y.league_rank));
  } else if (mode === "conference") {
    for (const [conf, list] of Object.entries(by("conf", rows)).sort()) {
      body += `<h2>${esc(conf)}</h2>` + standingsTable(list.sort((x, y) => x.conf_rank - y.conf_rank));
    }
  } else if (mode === "wildcard") {
    for (const [conf, list] of Object.entries(by("conf", rows)).sort()) {
      body += `<h2>${esc(conf)} Conference</h2>`;
      for (const [div, dl] of Object.entries(by("div", list)).sort()) {
        body += `<h2 style="margin-top:12px">${esc(div)}</h2>` + standingsTable(dl.filter(r => r.div_rank <= 3).sort((x, y) => x.div_rank - y.div_rank));
      }
      const wc = list.filter(r => r.div_rank > 3).sort((x, y) => x.wildcard - y.wildcard);
      body += `<h2 style="margin-top:12px">Wild card</h2>` + standingsTable(wc, { cutAfter: 2, rank: (r, i) => i < 2 ? `WC${i + 1}` : "" });
    }
    body += `<p class="help">Top three in each division plus two wild cards per conference make the playoffs. The dashed line is the cut.</p>`;
  } else {
    for (const [div, list] of Object.entries(by("div", rows)).sort()) {
      body += `<h2>${esc(div)}</h2>` + standingsTable(list.sort((x, y) => x.div_rank - y.div_rank));
    }
  }
  view.innerHTML = `${leaguePicker("nhl")}<div class="seg">${STANDING_MODES.map(([k, l]) => `<button data-mode="${k}" class="${k === mode ? "on" : ""}">${l}</button>`).join("")}</div>${body}`;
  bindLeaguePicker(() => standingsView(mode));
  view.querySelectorAll("[data-mode]").forEach(b => b.addEventListener("click", () => {
    try { localStorage.setItem("standingsMode", b.dataset.mode); } catch { /* fine */ }
    standingsView(b.dataset.mode);
  }));
}

// ---- Teams -------------------------------------------------------------------------------
async function teamsView() {
  setNav("teams");
  const lg = pageLeague();
  let rows = [];
  if (lg === "nhl") { try { rows = await standings(); } catch { /* fall back to a flat list */ } }
  const fav = favs();
  const tile = abbr => `<a class="tile" href="#/team/${abbr}">${mark(abbr)}${esc(teamName(abbr))}</a>`;
  let html = leaguePicker(lg);
  const mineHere = [...fav].filter(a => leagueOf(a) === lg);
  if (mineHere.length) html += `<h2>Your teams</h2><div class="grid">${mineHere.map(tile).join("")}</div>`;
  if (lg === "pwhl") {
    html += `<h2>PWHL</h2><div class="grid">${Object.keys(TEAMS).filter(a => leagueOf(a) === "pwhl").sort().map(tile).join("")}</div>`;
  } else if (rows.length) {
    const divs = {};
    rows.forEach(r => (divs[r.div] ||= []).push(r.abbr));
    for (const div of Object.keys(divs).sort()) html += `<h2>${esc(div)}</h2><div class="grid">${divs[div].sort().map(tile).join("")}</div>`;
  } else {
    html += `<h2>All teams</h2><div class="grid">${Object.keys(TEAMS).filter(a => leagueOf(a) === "nhl").map(tile).join("")}</div>`;
  }
  view.innerHTML = html;
  bindLeaguePicker(teamsView);
}

async function teamView(abbr) {
  setNav("teams");
  view.innerHTML = `<div class="empty">Loading ${esc(fullName(abbr))}…</div>`;
  let d, rows = [];
  try { [d, rows] = await Promise.all([api(`/api/team/${encodeURIComponent(abbr)}`), standings(leagueOf(abbr)).catch(() => [])]); }
  catch (e) { view.innerHTML = failed(e); return; }
  const st = rows.find(r => r.abbr === abbr);
  const fav = favs();
  const done = d.schedule.filter(g => g.state === "final").slice(-5).reverse();
  const next = d.schedule.filter(g => g.state !== "final").slice(0, 6);
  const dated = g => `<div class="subhead">${esc(shortDate(g.date))}</div>${gameCard(g, fav)}`;
  const isFav = fav.has(abbr);
  let html = `<div class="card pad" style="margin-top:12px;display:flex;align-items:center;gap:14px">
      ${mark(abbr, true)}
      <div style="flex:1"><h1 style="margin:0">${esc(fullName(abbr))}</h1>
      ${st && leagueOf(abbr) === "pwhl" ? `<div class="muted small">${st.w}-${st.otw}-${st.otl}-${st.l} · ${st.pts} pts · ${esc(ordinal(st.league_rank))} in the PWHL${st.season ? ` (${esc(st.season)})` : ""}</div>`
        : st ? `<div class="muted small">${st.w}-${st.l}-${st.otl} · ${st.pts} pts · ${esc(ordinal(st.div_rank))} in the ${esc(st.div)}</div>` : ""}</div>
      <button class="btn small" id="fav">${isFav ? "★ Favorite" : "☆ Favorite"}</button>
    </div>`;
  if (next.length) html += `<h2>Coming up</h2><div class="card">${next.map(dated).join("")}</div>`;
  if (done.length) html += `<h2>Recent results</h2><div class="card">${done.map(dated).join("")}</div>`;
  if (d.wire?.length) html += `<h2>News &amp; moves</h2><div class="card">${d.wire.slice(0, 8).map(i => wireItem(i, new Set())).join("")}</div>`;
  const sk = d.stats.skaters.slice(0, 10);
  if (sk.length) {
    html += `<h2>Leaders</h2><div class="card scroll"><table><tr><th>Skater</th><th>GP</th><th>G</th><th>A</th><th>P</th><th>+/-</th></tr>
      ${sk.map(p => `<tr><td>${esc(p.name)} <span class="muted small">${esc(p.pos)}</span></td><td>${p.gp}</td><td>${p.g}</td><td>${p.a}</td><td><b>${p.p}</b></td><td>${p.pm > 0 ? "+" : ""}${p.pm}</td></tr>`).join("")}
      </table>${d.stats.goalies.length ? `<table><tr><th>Goalie</th><th>GP</th><th>W-L-OT</th><th>GAA</th><th>SV%</th></tr>
      ${d.stats.goalies.map(p => `<tr><td>${esc(p.name)}</td><td>${p.gp}</td><td>${p.w}-${p.l}-${p.otl}</td><td>${p.gaa.toFixed(2)}</td><td>${p.svpct.toFixed(3).replace(/^0/, "")}</td></tr>`).join("")}</table>` : ""}</div>`;
  }
  if (d.roster.length) {
    const groups = { F: "Forwards", D: "Defense", G: "Goalies" };
    html += `<h2>Roster</h2><div class="card scroll"><table><tr><th>#</th><th>Player</th><th>Pos</th><th>Shoots</th><th>Born</th></tr>
      ${Object.entries(groups).map(([k, label]) => `<tr><td colspan="5" class="subhead">${label}</td></tr>` + d.roster.filter(p => p.group === k)
        .sort((x, y) => (x.number || 99) - (y.number || 99))
        .map(p => `<tr><td class="muted">${p.number ?? ""}</td><td>${esc(p.name)}</td><td>${esc(p.pos)}</td><td>${esc(p.shoots || "")}</td><td class="muted">${esc((p.born || "").slice(0, 4))} ${esc(p.country || "")}</td></tr>`).join("")).join("")}
      </table></div>`;
  }
  view.innerHTML = html;
  document.getElementById("fav").addEventListener("click", async () => {
    const list = new Set(ME.settings.favorites);
    list.has(abbr) ? list.delete(abbr) : list.add(abbr);
    ME.settings = await api("/api/settings", { method: "PUT", body: JSON.stringify({ ...ME.settings, favorites: [...list] }) });
    teamView(abbr);
  });
}

function ordinal(n) {
  if (!n) return "";
  const teen = n % 100 >= 11 && n % 100 <= 13;
  return `${n}${teen ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th")}`;
}

// ---- Settings -------------------------------------------------------------------------------
// Every tap saves straight away (no Save button). Saves queue up so they land in order; a toast says how it went.
let settingsQueue = Promise.resolve();
function saveSettings(patch) {
  ME.settings = { ...ME.settings, ...patch };
  const body = JSON.stringify(ME.settings);
  settingsQueue = settingsQueue.then(() => api("/api/settings", { method: "PUT", body }))
    .then(() => toast("Saved ✓"), () => toast("Couldn't save. Check your connection and try again.", true));
  return settingsQueue;
}

let toastTimer = null;
function toast(text, bad = false) {
  let el = document.getElementById("toast");
  if (!el) { el = document.createElement("div"); el.id = "toast"; el.setAttribute("role", "status"); document.body.append(el); }
  el.textContent = text;
  el.className = `toast show${bad ? " bad" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = "toast"; }, bad ? 4000 : 1400);
}

// NHL teams by division, then the PWHL (no divisions).
function teamGroups() {
  const groups = {};
  for (const [abbr, t] of Object.entries(TEAMS)) {
    const g = leagueOf(abbr) === "pwhl" ? "PWHL" : t.div || "NHL";
    (groups[g] ||= []).push(abbr);
  }
  const order = ["Atlantic", "Metropolitan", "Central", "Pacific", "NHL", "PWHL"];
  return order.filter(g => groups[g]).map(g => [g, groups[g].sort((a, b) => teamName(a).localeCompare(teamName(b)))]);
}

let editingTeams = false;
function settingsView() {
  setNav("settings");
  const s = ME.settings;
  const fav = s.favorites || [];
  const open = editingTeams || !fav.length;
  const local = (s.local || [])[0] || "";
  const services = s.services || [];
  const guess = !local && fav.find(a => leagueOf(a) === "nhl");
  const nhlGroups = teamGroups().filter(([g]) => g !== "PWHL");

  const mine = fav.length ? `<div class="myteams">${fav.map(a =>
    `<a class="myteam" href="#/team/${a}">${mark(a, true)}<span><b>${esc(fullName(a))}</b><span class="muted small">${leagueOf(a) === "pwhl" ? "PWHL" : esc(TEAMS[a]?.div || "NHL")}</span></span></a>`).join("")}</div>` : "";
  const picker = `<div class="team-picker">${teamGroups().map(([g, list]) => `<div class="subhead">${esc(g)}</div><div class="chips">${list.map(a =>
    `<label>${mark(a)}<input type="checkbox" name="favorites" value="${a}" ${fav.includes(a) ? "checked" : ""}>${esc(teamName(a))}</label>`).join("")}</div>`).join("")}</div>`;

  view.innerHTML = `
    <h1>Settings</h1>
    <p class="help" style="margin:-4px 2px 0">Changes save as you make them.</p>

    <div class="section-head"><h2>Your teams</h2>${fav.length ? `<button class="btn small" id="editteams">${open ? "Done" : "Edit"}</button>` : ""}</div>
    <div class="card">${open ? (fav.length ? "" : `<div class="pad small">Tap your teams. They're pinned to the top of Tonight, highlighted everywhere, and the ones you get alerts for.</div>`) + picker : mine}</div>
    ${open && fav.length ? `<p class="help">Tap a team again to remove it.</p>` : ""}

    <h2>Watching</h2>
    <div class="card">
      <label class="row-field"><span><b>Home market</b><span class="muted small">Whose games are blacked out on ESPN+ for you and shown on local TV instead</span></span>
        <select id="local" class="field"><option value="">None</option>${nhlGroups.map(([g, list]) => `<optgroup label="${esc(g)}">${list.map(a =>
          `<option value="${a}" ${a === local ? "selected" : ""}>${esc(fullName(a))}</option>`).join("")}</optgroup>`).join("")}</select></label>
      ${guess ? `<div class="pad small suggest">Live near ${esc(TEAMS[guess].place)}? <button class="btn small" id="useguess">Use the ${esc(teamName(guess))}</button></div>` : ""}
      <div class="subhead">What you can watch with</div>
      <div class="checks">${Object.entries(ME.services).map(([k, v]) =>
        `<label><input type="checkbox" name="services" value="${k}" ${services.includes(k) ? "checked" : ""}>${esc(v.label)}</label>`).join("")}</div>
    </div>
    <p class="help">Each game then says "You have it" or "Not in your services". In Massachusetts the home market is the Bruins.</p>

    <h2>Alerts</h2>
    <div class="card" id="notif"><div class="empty">Checking this device…</div></div>
    <div class="card checks" style="margin-top:10px">${[["start", "Puck drop"], ["goals", "Every goal"], ["final", "Final scores"], ["trades", "Trades"]].map(([k, l]) =>
      `<label><input type="checkbox" name="notify" value="${k}" ${s.notify?.[k] !== false ? "checked" : ""}>${l}</label>`).join("")}</div>
    <p class="help">For your teams only. New here? <a href="#/app">How to get the app and alerts on your phone</a>.</p>

    <h2>Calendar</h2>
    <div class="card" id="cal"><div class="empty">Loading…</div></div>
    <p class="help">Every game for your teams, with where to watch in each event. Your phone's calendar checks it every few hours. The link is personal; don't share it.</p>

    <h2>Help</h2>
    <a class="card pad whatsnew-link" href="#/report"><b>Report a problem or suggest an idea</b><span class="muted small">Goes straight to the to-do list →</span></a>
    <div id="myreports"></div>
    <a class="card pad whatsnew-link" href="#/new" style="margin-top:10px"><b>What's new</b>${unseenChanges().length ? ` <span class="pill info">${unseenChanges().length} new</span>` : ""}<span class="muted small">Every update to the app →</span></a>
    <p class="help" style="margin-top:12px">Signed in as ${esc(ME.email)}.</p>`;
  showCalendar();
  showNotifications();
  showMyReports("myreports");

  const picked = name => [...view.querySelectorAll(`input[name=${name}]:checked`)].map(i => i.value);
  document.getElementById("editteams")?.addEventListener("click", () => { editingTeams = !open; settingsView(); });
  view.querySelectorAll("input[name=favorites]").forEach(i => i.addEventListener("change", () => {
    // Keep the order people picked them in: existing picks first, new ones on the end.
    const now = new Set(picked("favorites"));
    const had = ME.settings.favorites.length;
    editingTeams = true;
    saveSettings({ favorites: [...ME.settings.favorites.filter(a => now.has(a)), ...[...now].filter(a => !ME.settings.favorites.includes(a))] })
      .then(showCalendar);
    if (!had !== !now.size) settingsView();  // first pick / last removal: the Done button and the home-market hint change
  }));
  document.getElementById("local").addEventListener("change", e => {
    saveSettings({ local: e.target.value ? [e.target.value] : [] });
    document.querySelector(".suggest")?.remove();
  });
  document.getElementById("useguess")?.addEventListener("click", () => { saveSettings({ local: [guess] }); settingsView(); });
  view.querySelectorAll("input[name=services]").forEach(i => i.addEventListener("change", () => saveSettings({ services: picked("services") })));
  view.querySelectorAll("input[name=notify]").forEach(i => i.addEventListener("change", () => {
    const on = new Set(picked("notify"));
    saveSettings({ notify: Object.fromEntries(["start", "goals", "final", "trades"].map(k => [k, on.has(k)])) });
  }));
}

// ---- Bug reports ------------------------------------------------------------------------------
// Filed as GitHub issues by the server, without anyone's name or email. "Your reports" shows their state.
let reportFrom = "#/";   // the page someone was on when they tapped "Report it"

function deviceLabel() {
  const ua = navigator.userAgent;
  const os = { ios: /iPad/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1) ? "iPad" : "iPhone",
    "ios-other": "iPhone", android: "Android", desktop: /Mac/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows" : /Linux/.test(ua) ? "Linux" : "Computer" }[device()];
  const browser = /EdgiOS|Edg\//.test(ua) ? "Edge" : /CriOS|Chrome\//.test(ua) ? "Chrome" : /FxiOS|Firefox\//.test(ua) ? "Firefox"
    : /Safari\//.test(ua) ? "Safari" : "browser";
  return `${os} · ${browser}${isStandalone() ? " · home-screen app" : ""} · ${window.innerWidth}px wide`;
}

const REPORT_STATE = { open: ["Open", "info"], fixed: ["Fixed", "have"], closed: ["Closed", "need"] };
function reportList(reports) {
  if (!reports.length) return "";
  return `<div class="card">${reports.map(r => {
    const [label, cls] = REPORT_STATE[r.state] || REPORT_STATE.open;
    return `<a class="report-row" href="${esc(r.url || "#")}" target="_blank" rel="noopener">
      <span class="report-head"><span class="pill ${cls}">${label}</span><b>${esc(r.title)}</b></span>
      <span class="muted small">${r.kind === "idea" ? "Idea" : "Bug"} #${r.issue} · sent ${esc(new Date(r.created).toLocaleDateString(undefined, { month: "short", day: "numeric" }))}</span>
      ${r.reply ? `<span class="report-reply small"><b>Reply:</b> ${esc(r.reply.length > 280 ? r.reply.slice(0, 279) + "…" : r.reply)}</span>` : ""}
    </a>`;
  }).join("")}</div>`;
}

async function showMyReports(boxId) {
  const box = document.getElementById(boxId);
  if (!box) return;
  const d = await api("/api/bugs").catch(() => null);
  if (!d) { box.innerHTML = ""; return; }
  box.innerHTML = d.reports.length ? `<h2>Your reports</h2>${reportList(d.reports)}<p class="help">Tap one to see it on GitHub. It says Fixed once it's been sorted out.</p>` : "";
}

function reportView(kind = "bug") {
  setNav("");
  const page = reportFrom;
  view.innerHTML = `
    <h1>Report a problem</h1>
    <div class="seg" role="group" aria-label="Kind">
      <button data-kind="bug" class="${kind === "bug" ? "on" : ""}">Something's wrong</button>
      <button data-kind="idea" class="${kind === "idea" ? "on" : ""}">I have an idea</button>
    </div>
    <div class="card pad">
      <textarea id="bugtext" class="field bugtext" rows="7" maxlength="4000" placeholder="${kind === "idea"
        ? "What would make the app better?" : "What happened, and what did you expect instead? Which game or team, if it's about one."}"></textarea>
      <p class="help" style="margin-top:10px">Sent with it: the page you were on (<code>${esc(page)}</code>), ${esc(deviceLabel())}, and the app version. Not your name or email.</p>
      <p class="help"><b>Reports are posted publicly on GitHub</b>, so leave out anything private.</p>
      <div style="display:flex;gap:10px;align-items:center;margin-top:12px;flex-wrap:wrap">
        <button class="btn primary" id="bugsend">Send</button><a href="${esc(page)}" class="small">Cancel</a>
      </div>
      <p class="help" id="bugmsg" role="status"></p>
    </div>
    <div id="myreports"></div>`;
  view.querySelectorAll("[data-kind]").forEach(b => b.addEventListener("click", () => {
    const text = document.getElementById("bugtext").value;
    reportView(b.dataset.kind);
    document.getElementById("bugtext").value = text;
  }));
  const msg = t => { document.getElementById("bugmsg").textContent = t; };
  document.getElementById("bugsend").addEventListener("click", async e => {
    const text = document.getElementById("bugtext").value.trim();
    if (text.length < 10) { msg("Tell us a bit more (at least a sentence)."); return; }
    e.target.disabled = true;
    msg("Sending…");
    try {
      const r = await api("/api/bug", { method: "POST", body: JSON.stringify({ kind, text, page, device: deviceLabel() }) });
      if (r.link) {  // this install isn't connected to GitHub: hand over GitHub's own form, filled in
        window.open(r.link, "_blank", "noopener");
        msg("Opened GitHub's form in a new tab (you'll need a GitHub account there).");
        e.target.disabled = false;
        return;
      }
      view.innerHTML = `<h1>Thanks!</h1>
        <div class="card pad"><p style="margin-top:0">It's in as <a href="${esc(r.url)}" target="_blank" rel="noopener">#${r.issue}: ${esc(r.title)}</a>.</p>
        <p class="help">You can follow it under <a href="#/settings">Settings → Your reports</a>; it says Fixed once it's been sorted out.</p>
        <div class="links" style="margin-top:12px"><a class="btn primary" href="${esc(page)}">Back to where I was</a></div></div>`;
    } catch (err) {
      msg(err.detail || "Couldn't send it. Check your connection and try again.");
      e.target.disabled = false;
    }
  });
  showMyReports("myreports");
}

function b64ToBytes(b64) {
  const s = atob(b64.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - b64.length % 4) % 4));
  return Uint8Array.from(s, c => c.charCodeAt(0));
}

async function showNotifications() {
  const box = document.getElementById("notif");
  if (!box) return;
  const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent);
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    box.innerHTML = `<div class="pad small">${ios && !standalone
      ? "On iPhone, alerts only work from the home-screen app. Do step 1 first, open Shots on Goal from your home screen, then come back here."
      : "This browser can't receive notifications."}${location.hash !== "#/app" ? ` <a href="#/app">Show me how</a>` : ""}</div>`;
    return;
  }
  // ready never settles if the service worker failed to install, so don't wait forever.
  const reg = await Promise.race([navigator.serviceWorker.ready, new Promise(r => setTimeout(() => r(null), 5000))]);
  if (!reg) {
    box.innerHTML = `<div class="pad small">Couldn't check this device. Reload the page and try again.</div>`;
    return;
  }
  const sub = await reg.pushManager.getSubscription();
  const info = await api("/api/push").catch(() => null);
  const blocked = Notification.permission === "denied";
  box.innerHTML = `<div class="pad">
    <p class="small" style="margin:0 0 10px">${blocked ? "Notifications are blocked for this site in your browser settings."
      : sub ? "On for this device." : "Off for this device."}${info?.devices ? ` <span class="muted">(${info.devices} device${info.devices > 1 ? "s" : ""} signed up)</span>` : ""}</p>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      ${blocked ? "" : sub ? `<button class="btn" id="pushoff">Turn off here</button><button class="btn" id="pushtest">Send a test</button>`
        : `<button class="btn primary" id="pushon">Turn on for this device</button>`}
    </div><p class="help" id="pushmsg"></p></div>`;
  const msg = t => { document.getElementById("pushmsg").textContent = t; };
  document.getElementById("pushon")?.addEventListener("click", async e => {
    e.target.disabled = true;
    try {
      if (await Notification.requestPermission() !== "granted") { msg("Permission wasn't given."); e.target.disabled = false; return; }
      const s2 = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(info.key) });
      await api("/api/push/subscribe", { method: "POST", body: JSON.stringify({ subscription: s2.toJSON() }) });
      showNotifications();
    } catch (err) { msg(`Couldn't turn them on: ${err.message || err}`); e.target.disabled = false; }
  });
  document.getElementById("pushoff")?.addEventListener("click", async () => {
    await api("/api/push/unsubscribe", { method: "POST", body: JSON.stringify({ endpoint: sub.endpoint }) }).catch(() => {});
    await sub.unsubscribe();
    showNotifications();
  });
  document.getElementById("pushtest")?.addEventListener("click", async e => {
    e.target.disabled = true;
    const r = await api("/api/push/test", { method: "POST" }).catch(() => ({ sent: 0 }));
    msg(r.sent ? "Sent. It should pop up in a few seconds." : "Couldn't deliver it. Try turning notifications off and on again.");
    e.target.disabled = false;
  });
}

async function showCalendar() {
  const box = document.getElementById("cal");
  if (!box) return;
  const teams = ME.settings.favorites;
  if (!teams.length) { box.innerHTML = `<div class="empty">Pick some favorite teams first.</div>`; return; }
  let c;
  try { c = await api("/api/calendar"); } catch { box.innerHTML = `<div class="empty">Couldn't make a calendar link.</div>`; return; }
  const https = `${c.base}/cal/${c.token}/${teams.join("+")}.ics`;
  const webcal = https.replace(/^https?:/, "webcal:");
  box.innerHTML = `<div class="links" style="padding-top:14px"><a class="btn primary" href="${esc(webcal)}">Subscribe (${esc(teams.map(teamName).join(", "))})</a></div>
    <div class="copyrow"><input class="field" readonly value="${esc(https)}"><button class="btn" id="copycal">Copy</button></div>`;
  document.getElementById("copycal").addEventListener("click", async e => {
    try { await navigator.clipboard.writeText(https); e.target.textContent = "Copied"; } catch { prompt("Copy this link:", https); }
  });
}

// ---- Admin ---------------------------------------------------------------------------------
const ago = iso => {
  if (!iso) return "";
  const m = Math.round((Date.now() - Date.parse(iso)) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  if (m < 1440) return `${Math.round(m / 60)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

async function adminView() {
  setNav("admin");
  if (!ME.admin) { view.innerHTML = `<div class="empty">Admin only.</div>`; return; }
  let d;
  try { d = await api("/api/admin"); } catch (e) { view.innerHTML = failed(e); return; }
  const people = st => d.users.filter(u => u.status === st);
  const row = (u, buttons) => `<div class="person"><span class="em">${esc(u.email)}</span><span class="when">${esc(ago(u.requested || u.decided))}</span>${buttons}</div>`;
  const btn = (email, status, label, primary) => `<button class="btn small${primary ? " primary" : ""}" data-email="${esc(email)}" data-status="${status}">${label}</button>`;
  const pending = people("pending"), approved = people("approved"), other = d.users.filter(u => ["denied", "revoked"].includes(u.status));
  const openInvites = d.invites.filter(i => i.uses.length < i.max_uses);
  view.innerHTML = `
    <h1>Admin</h1>
    <h2>Waiting for approval</h2>
    <div class="card">${pending.length ? pending.map(u => row(u, btn(u.email, "approved", "Approve", true) + btn(u.email, "denied", "Deny"))).join("") : `<div class="empty">Nobody waiting.</div>`}</div>
    ${d.reports.filter(r => !r.resolved).length ? `<h2>Wrong-channel reports</h2><div class="card">${d.reports.filter(r => !r.resolved).map(r => `<div class="person">
      <span class="em">${esc(r.game)}<div class="when">Showed ${esc(r.shown)}${r.note ? ` · "${esc(r.note)}"` : ""} · ${esc(r.email)}, ${esc(ago(r.created))}</div></span>
      <a class="btn small" href="#/game/${r.game_id}">Game</a><button class="btn small" data-resolve="${r.id}">Done</button></div>`).join("")}</div>` : ""}
    <h2>Invite a friend</h2>
    <div class="card"><div class="copyrow"><input class="field" id="note" placeholder="Who it's for (optional)"><input class="field" id="uses" type="number" min="1" max="50" value="1" inputmode="numeric" aria-label="How many people" title="How many people can use it" style="flex:none;width:4.5em"><button class="btn primary" id="mkinvite">Make link</button></div>
      <div id="newlink"></div>
      ${openInvites.map(i => `<div class="person"><span class="em">${esc(i.note || "Unnamed invite")}
          <div class="when">${i.max_uses > 1 ? `${i.uses.length} of ${i.max_uses} joined` : "For one person"}${i.uses.length ? `: ${i.uses.map(u => esc(u.email)).join(", ")}` : ""}</div></span>
        <span class="when">${esc(ago(i.created))}</span>
        <button class="btn small" data-copy="${esc(i.link)}">Copy link</button><button class="btn small" data-del="${esc(i.code)}">${i.uses.length ? "Close" : "Delete"}</button></div>`).join("")}</div>
    <p class="help">Set how many people can use a link (one for a single friend, more for a group chat). Whoever signs in with it is approved straight away. Close a group link to stop it.</p>
    <h2>Approved (${approved.length})</h2>
    <div class="card">${approved.map(u => row(u, ME.email === u.email ? `<span class="pill info">You</span>` : btn(u.email, "revoked", "Revoke"))).join("")}</div>
    ${other.length ? `<h2>Denied or revoked</h2><div class="card">${other.map(u => row(u, btn(u.email, "approved", "Approve"))).join("")}</div>` : ""}
    <h2>Insiders on the Wire (${d.insiders.length})</h2>
    <div class="card">
      <div class="copyrow"><input class="field" id="handle" placeholder="Bluesky handle, e.g. russohockey">
        <select class="field" id="insleague" style="flex:none;width:auto"><option value="nhl">NHL</option><option value="pwhl">PWHL</option></select>
        <button class="btn primary" id="addins">Add</button></div>
      <div id="inserr" class="help" style="padding:0 14px"></div>
      ${d.insiders.map(i => `<div class="person"><span class="em"><span class="pill info">${esc(LEAGUE_NAME[i.league] || "NHL")}</span> ${esc(i.label)}<div class="when">@${esc(i.handle)}</div></span>
        <a class="btn small" href="https://bsky.app/profile/${esc(i.handle)}" target="_blank" rel="noopener">View</a>
        <button class="btn small" data-rmins="${esc(i.handle)}">Remove</button></div>`).join("")}
    </div>
    <h2>Data sources</h2>
    <div class="card scroll"><table><tr><th>Source</th><th>Last success</th><th>Status</th></tr>
      ${Object.values(d.sources).map(s => `<tr><td>${esc(s.source)}</td><td>${esc(ago(s.last_ok))}</td><td>${s.error ? `<span class="pill need" title="${esc(s.error)}">Failing</span>` : `<span class="pill have">OK</span>`}</td></tr>`).join("")}
    </table></div>`;
  view.querySelectorAll("[data-status]").forEach(b => b.addEventListener("click", async () => {
    b.disabled = true;
    await api("/api/admin/users", { method: "POST", body: JSON.stringify({ email: b.dataset.email, status: b.dataset.status }) });
    adminView();
  }));
  const copy = async (text, b) => {
    try { await navigator.clipboard.writeText(text); b.textContent = "Copied"; } catch { prompt("Copy this link:", text); }
  };
  view.querySelectorAll("[data-copy]").forEach(b => b.addEventListener("click", () => copy(b.dataset.copy, b)));
  view.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", async () => {
    await api(`/api/admin/invites/${encodeURIComponent(b.dataset.del)}`, { method: "DELETE" });
    adminView();
  }));
  view.querySelectorAll("[data-resolve]").forEach(b => b.addEventListener("click", async () => {
    await api(`/api/admin/reports/${b.dataset.resolve}/resolve`, { method: "POST" });
    adminView();
  }));
  view.querySelectorAll("[data-rmins]").forEach(b => b.addEventListener("click", async () => {
    await api(`/api/admin/insiders/${encodeURIComponent(b.dataset.rmins)}`, { method: "DELETE" });
    adminView();
  }));
  document.getElementById("addins").addEventListener("click", async e => {
    e.target.disabled = true;
    try {
      await api("/api/admin/insiders", { method: "POST", body: JSON.stringify({ handle: document.getElementById("handle").value,
        league: document.getElementById("insleague").value }) });
      adminView();
    } catch (err) {
      document.getElementById("inserr").textContent = err.detail || "Couldn't add that account.";
      e.target.disabled = false;
    }
  });
  document.getElementById("mkinvite").addEventListener("click", async () => {
    const r = await api("/api/admin/invites", { method: "POST", body: JSON.stringify({ note: document.getElementById("note").value, uses: +document.getElementById("uses").value || 1 }) });
    await adminView();
    document.getElementById("newlink").innerHTML = `<div class="copyrow"><input class="field" readonly value="${esc(r.link)}"><button class="btn" id="copynew">Copy</button></div>`;
    document.getElementById("copynew").addEventListener("click", e => copy(r.link, e.target));
  });
}

// ---- router ---------------------------------------------------------------------------------
function route() {
  clearTimeout(refreshTimer);
  if (ME.status !== "approved") return gateView();
  document.getElementById("tabs").hidden = false;
  document.getElementById("admin-tab").hidden = !ME.admin;
  const [, page, arg] = (location.hash || "#/").split("/");
  if (page !== "settings") editingTeams = false;
  if (page !== "report") reportFrom = location.hash || "#/";
  document.getElementById("foot").hidden = page === "report";
  window.scrollTo(0, 0);
  if (page === "day" && /^\d{4}-\d{2}-\d{2}$/.test(arg || "")) return tonightView(arg);
  if (page === "game" && /^\d+$/.test(arg || "")) return gameView(arg);
  if (page === "pgame" && /^\d+$/.test(arg || "")) return gameView(arg, false, "pwhl");
  if (page === "wire") return wireView();
  if (page === "standings") {
    let mode = "division";
    try { mode = localStorage.getItem("standingsMode") || mode; } catch { /* fine */ }
    return standingsView(mode);
  }
  if (page === "teams") return teamsView();
  if (page === "team" && /^(PW-)?[A-Z]{2,3}$/.test(arg || "")) return teamView(arg);
  if (page === "settings") return settingsView();
  if (page === "app") return appView();
  if (page === "new") return whatsNewView();
  if (page === "report") return reportView();
  if (page === "admin") return adminView();
  return tonightView();
}

async function start() {
  try {
    ME = await api("/api/me");
  } catch {
    view.innerHTML = `<div class="notice error">Couldn't reach Shots on Goal. Check your connection and reload.</div>`;
    return;
  }
  TEAMS = Object.fromEntries(ME.teams.map(t => [t.abbr, t]));
  if (ME.status === "approved") CHANGES = await api("/api/changes").catch(() => []);
  updateNewDot();
  const asked = new URLSearchParams(location.search).get("league");  // a shared link can pick the league
  if (["nhl", "pwhl", "both"].includes(asked)) { LEAGUE = asked; try { localStorage.setItem("league", asked); } catch { /* fine */ } }
  applyLeague();
  document.querySelectorAll("[data-league]").forEach(b => b.addEventListener("click", () => setLeague(b.dataset.league)));
  window.addEventListener("hashchange", route);
  // Phones keep the app's last page in memory for days: coming back after a while shows today, not last night.
  let hiddenAt = 0;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { hiddenAt = Date.now(); return; }
    if (hiddenAt && Date.now() - hiddenAt > 5 * 60000) route();
  });
  route();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
}

start();
