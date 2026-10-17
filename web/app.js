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

// The phone's own copy of every page's data (path -> {at, data}). Tabs open from it instantly and refresh behind
// the scenes; anything that changes data (a pick, a setting, a reaction) clears it so nothing old shows.
const GET_CACHE = new Map();
const SHOW_COPY_FOR = 30 * 60000;   // older copies wait for fresh data instead
const FRESH_WAIT = 150;             // ms a page waits for fresh data before drawing the phone's copy

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { Accept: "application/json", "Content-Type": "application/json" }, ...opts });
  if (PI_DOWN(r.status)) goOffline();
  if (!r.ok) {
    const err = new Error(`${path}: ${r.status}`);
    err.status = r.status;
    try { err.detail = (await r.json()).detail; } catch { /* not JSON */ }
    throw err;
  }
  const data = await r.json();
  if (!opts.method || opts.method === "GET") GET_CACHE.set(path, { at: Date.now(), data });
  else GET_CACHE.clear();
  return data;
}

// A page's data, fast: the phone's copy straight away (then `rerender` once if the fresh data differs), or the
// network when there's no usable copy. `quiet` (the auto-refresh) always waits for fresh data.
async function fast(path, rerender, quiet = false) {
  const hit = GET_CACHE.get(path), age = hit ? Date.now() - hit.at : Infinity;
  if (age < 3000) return hit.data;                              // just fetched (this is the re-render)
  if (quiet || age > SHOW_COPY_FOR) return api(path);
  // Give fresh data a head start: on a decent connection it lands within 150 ms, so the page draws once, already
  // current, and nothing changes after the animation. Only a slow answer falls back to the phone's copy.
  const route = location.hash, fresh = api(path);
  const first = await Promise.race([fresh.then(d => ({ d }), () => null), new Promise(r => setTimeout(() => r(null), FRESH_WAIT))]);
  if (first) return first.d;
  fresh.then(async d => {
    if (location.hash !== route || JSON.stringify(d) === JSON.stringify(hit.data)) return;
    await Promise.all(view.getAnimations().map(a => a.finished.catch(() => {})));  // never redraw mid-animation
    if (location.hash === route) rerender();
  }).catch(() => {});
  return hit.data;
}

// After the app opens: load the other tabs and your teams' pages in the background, a few at a time, so every
// tab after the first opens from the phone's copy.
async function prefetch() {
  if (ME?.status !== "approved") return;
  const leagues = LEAGUE === "both" ? ["nhl", "pwhl"] : [LEAGUE];
  let wire = { kind: "", mine: false };
  try { wire = { ...wire, ...JSON.parse(localStorage.getItem("wire") || "{}") }; } catch { /* defaults */ }
  const paths = [`/api/pickem?leagues=${leagues.join(",")}`,
    ...leagues.map(l => `/api/wire?league=${l}&kind=${wire.kind}&mine=${wire.mine ? 1 : 0}`),
    ...(ME.settings.favorites || []).map(a => `/api/team/${encodeURIComponent(a)}`), "/api/search"];
  standings(pageLeague()).catch(() => {});
  for (const path of paths) {
    if (document.hidden) return;
    const hit = GET_CACHE.get(path);
    if (!hit || Date.now() - hit.at > 60000) await api(path).catch(() => {});
  }
}
// While the app is open and visible, keep those copies under ~90 s old, so a tab rarely has to catch up after opening.
setInterval(() => { if (!document.hidden) prefetch(); }, 90000);

const favs = () => new Set(ME?.settings?.favorites || []);

// A team's mark: its coloured badge, or (Settings > Display) its logo. A logo that can't load falls back to the badge.
function mark(abbr, big = false) {
  const t = TEAMS[abbr] || {};
  const cls = `mark${t.light ? " light" : ""}${big ? " big" : ""}`, code = esc(t.code || abbr);
  if (ME?.settings?.marks !== "logos" || !TEAMS[abbr]) return `<span class="${cls}" style="--c:${esc(t.color || "#666")}">${code}</span>`;
  const img = leagueOf(abbr) === "pwhl"
    ? `<img src="/img/logo/${abbr}-96.webp" alt="" loading="lazy" decoding="async">`
    : `<picture><source srcset="/img/logo/${abbr}-dark.svg" media="(prefers-color-scheme: dark)"><img src="/img/logo/${abbr}-light.svg" alt="" loading="lazy" decoding="async"></picture>`;
  return `<span class="${cls} logo" style="--c:${esc(t.color || "#666")}" title="${esc(fullName(abbr))}"><span class="code">${code}</span>${img}</span>`;
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


// Game page "Watch" group: one heading, the why, and one button per app (the links aren't repeated as text).
// Recap and tickets live here too, since they're the other ways of watching.
function watchBlock(g, report) {
  const w = g.watch, links = g.state !== "final" ? w?.links || [] : [];
  const ctx = w && g.state !== "final" ? [!links.length && (w.app || w.network) ? `<b>${esc(w.app || w.network)}</b>` : "", esc(w.why || "")].filter(Boolean).join(" · ") : "";
  const pill = !w || g.state === "final" ? "" : w.have === true ? `<span class="pill have">You have it</span>`
    : w.have === false ? `<span class="pill need">Not in your services</span>` : "";
  const btns = [
    ...links.map((l, i) => `<a class="btn${i ? "" : " primary"}" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.name)} ↗</a>`),
    g.recap ? `<a class="btn" href="${esc(g.recap)}" target="_blank" rel="noopener">Recap on NHL.com ↗</a>` : "",
    g.state === "pre" && g.tickets ? `<a class="btn" href="${esc(g.tickets)}" target="_blank" rel="noopener">Tickets ↗</a>` : ""].join("");
  if (!ctx && !btns && !report) return "";
  return `<div class="gsec">
    <div class="gsec-ctx"><span class="gsec-h">Watch</span>${ctx ? `<span>${ctx}</span>` : ""}${pill}</div>
    ${btns || report ? `<div class="gsec-row">${btns}${report}</div>` : ""}</div>`;
}
// ---- spoiler-free ------------------------------------------------------------------------------
// settings.spoilers = {teams: always hidden, games: "watching later", seen: watched since}. Mirrors sog/spoilers.py.
// Only started games from today or yesterday are hidden, so it switches itself off the day after.
const spKey = g => `${g.league === "pwhl" ? "pwhl" : "nhl"}:${g.id}`;
const peeked = new Set();         // "Show it now": for this visit only
const SPOIL_GAMES = new Map();    // key -> game, for the buttons
const isoDay = (offset = 0) => { const d = new Date(); d.setDate(d.getDate() + offset); return d.toLocaleDateString("en-CA"); };
const spoilers = () => ({ teams: [], games: [], seen: [], ...(ME.settings.spoilers || {}) });
function spoilerMarked(g) {
  const sp = spoilers(), k = spKey(g);
  if (!g || sp.seen.includes(k) || (g.date || "") < isoDay(-1)) return false;
  return sp.games.includes(k) || sp.teams.includes(g.away.abbr) || sp.teams.includes(g.home.abbr);
}
const spoilerHidden = g => !!g && ["live", "final"].includes(g.state) && !peeked.has(spKey(g)) && spoilerMarked(g);
const vsLine = g => `${TEAMS[g.away.abbr]?.code || g.away.abbr} vs ${TEAMS[g.home.abbr]?.code || g.home.abbr}`;
function spoilButton(action, g, label, primary = false) {
  SPOIL_GAMES.set(spKey(g), g);
  return `<button class="btn small${primary ? " primary" : ""}" data-spoil="${action}" data-k="${esc(spKey(g))}">${label}</button>`;
}
function spoilerAction(action, k) {
  const sp = spoilers(), g = SPOIL_GAMES.get(k);
  const drop = (list, x) => list.filter(y => y !== x);
  if (action === "peek") { peeked.add(k); return route(); }
  if (action === "peekall") { (k || "").split(",").forEach(x => peeked.add(x)); return route(); }
  if (action === "later") saveSettings({ spoilers: { ...sp, games: [...drop(sp.games, k), k], seen: drop(sp.seen, k) } });
  if (action === "seen") saveSettings({ spoilers: { ...sp, games: drop(sp.games, k), seen: [...drop(sp.seen, k), k] } });
  if (g && action === "later") toast(`Spoiler-free on for ${vsLine(g)}`);
  hiddenCache = { at: 0, list: [] };
  route();
}
// Today's hidden games, for pages that don't load the slate themselves (Wire, League, team pages): one request,
// skipped entirely when spoiler-free isn't in use, and run alongside the page's own request.
let hiddenCache = { at: 0, list: [] };
async function hiddenToday() {
  const sp = spoilers();
  if (!sp.teams.length && !sp.games.length) return [];
  if (Date.now() - hiddenCache.at > 60000) hiddenCache = { at: Date.now(), list: (await api("/api/hidden")).games };
  return hiddenCache.list.filter(spoilerHidden);
}
// A whole page that would give a hidden result away (standings, a team's page).
function spoilCover(games, what, verb = "includes") {
  return `<div class="card pad spoil-cover"><div class="spoil-eye">🙈</div>
    <p><b>${esc(what)}</b> ${verb} ${games.length > 1 ? "results" : "the result"} you're hiding: ${esc(games.map(vsLine).join(", "))}.</p>
    <button class="btn small" data-spoil="peekall" data-k="${esc(games.map(spKey).join(","))}">Show anyway</button></div>`;
}

function gameCard(g, fav) {
  const a = g.away, h = g.home, hide = spoilerHidden(g), done = g.state === "final" && !hide;
  const lost = side => done && a.score != null && h.score != null && side.score < (side === a ? h.score : a.score) ? " lost" : "";
  const sc = t => g.state === "pre" || g.state === "postponed" || hide ? "" : `<span class="sc">${t.score ?? ""}</span>`;
  const isFav = fav.has(a.abbr) || fav.has(h.abbr);
  // The watch line sits outside the game link so its own link (ESPN+, NESN 360...) can be tapped.
  return `<div class="game${isFav ? " fav" : ""}">
    <a class="body" href="${gameHref(g)}">
      <div class="team-line${lost(a)}">${mark(a.abbr)}<span class="nm">${esc(a.name || teamName(a.abbr))}</span>${sc(a)}</div>
      ${hide ? `<div class="status"><div class="t">🙈 Hidden</div></div>` : statusCell(g)}
      <div class="team-line${lost(h)}">${mark(h.abbr)}<span class="nm">${esc(h.name || teamName(h.abbr))}</span>${sc(h)}</div>
    </a>
    ${cardWatch(g.watch, g)}${oddsLine(g)}${watchersLine(g)}
  </div>`;
}

// "👀 Dave, Mike and you": friends who tapped I'm watching (until the game ends).
const namesList = list => { const n = list.map(w => w.me ? "you" : w.name); return n.length > 1 ? `${n.slice(0, -1).join(", ")} and ${n.at(-1)}` : n[0] || ""; };
const watchersLine = g => g.watching?.length && g.state !== "final" ? `<div class="watchers">👀 ${esc(namesList(g.watching))} watching</div>` : "";

// One short line on cards: the app to open and whether you have it. The why (blackouts, markets) and tickets
// are on the game page.
function cardWatch(w, g) {
  if (!w || g.state === "final") return "";
  const links = w.links || [];
  const name = links.length ? links.map(l => `<a class="app" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.name)} ↗</a>`).join(`<span>or</span>`)
    : w.app || w.network ? `<span class="app">${esc(w.app || w.network)}</span>` : "";
  if (!name) return w.why ? `<div class="watch"><span>${esc(w.why)}</span></div>` : "";
  const have = w.have === true ? `<span class="ok">✓ You have it</span>` : w.have === false ? `<span class="no">Not in your services</span>` : "";
  return `<div class="watch">${name}${have}</div>`;
}

// Odds, for fun only (sog/odds.py): who's favoured and how many goals are expected, from the last DraftKings line
// before puck drop. No sportsbook links. Off with Settings > Display > Show odds.
const oddsOn = () => ME?.settings?.odds !== false;
const SCORING_WORD = { high: "High-scoring game expected", low: "Low-scoring game expected" };
function favLine(o) {
  if (!o?.away_pct) return "";
  return o.fav ? `${teamName(o.fav)} favoured` : "Even matchup";
}
function oddsLine(g) {
  const o = g.odds;
  if (!oddsOn() || !o || spoilerHidden(g)) return "";
  if (g.state === "final") return o.upset ? `<div class="odds"><span class="upset">⚡ Upset!</span></div>` : "";
  if (g.state !== "pre") return "";
  const parts = [o.fav ? `${esc(favLine(o))} · ${Math.max(o.away_pct, o.home_pct)}%` : esc(favLine(o)), esc(SCORING_WORD[o.scoring] || "")].filter(Boolean);
  return parts.length ? `<div class="odds">${parts.join(" · ")}</div>` : "";
}
// Game page: win chances as a two-colour bar, expected goals, and whether a final was an upset.
function oddsBlock(g, ac, hc) {
  const o = g.odds;
  if (!oddsOn() || !o || (g.state !== "pre" && !(g.state === "final" && o.upset != null))) return "";
  const a = g.away.abbr, h = g.home.abbr;
  ac = apart(ac, hc);
  const bar = o.away_pct ? `<div class="oddsbar" role="img" aria-label="${esc(teamName(a))} ${o.away_pct}%, ${esc(teamName(h))} ${o.home_pct}%">
      <span style="--c:${esc(ac)};flex:${o.away_pct}">${esc(TEAMS[a]?.code || a)} ${o.away_pct}%</span>
      <span style="--c:${esc(hc)};flex:${o.home_pct}">${o.home_pct}% ${esc(TEAMS[h]?.code || h)}</span></div>` : "";
  let text;
  if (g.state === "final") {
    const dog = o.fav === a ? h : a;
    text = o.upset ? `⚡ <b>Upset!</b> The ${esc(teamName(dog))} won as the underdog (${dog === a ? o.away_pct : o.home_pct}% before puck drop).`
      : `The ${esc(teamName(o.fav))} won as the favourite.`;
  } else {
    text = [o.away_pct ? `<b>${esc(favLine(o))}</b>` : "", o.total != null ? `About ${o.total} goals expected${o.scoring !== "average" ? ` (${o.scoring}-scoring)` : ""}` : ""]
      .filter(Boolean).join(" · ");
  }
  return `<div class="gsec"><div class="gsec-h">Odds · just for fun</div>${g.state === "pre" ? bar : ""}<div class="gsec-ctx">${text}</div>
    <div class="odds-src">Win chances from DraftKings, with the bookmaker's cut taken out.</div></div>`;
}

// "Loading…" only when a page takes a moment: fast loads swap straight from the old page to the new one, no flash.
function showLoading(text) {
  const before = view.firstElementChild;
  setTimeout(() => { if (view.firstElementChild === before) view.innerHTML = `<div class="empty">${text}</div>`; }, 350);
}

function setNav(name) {
  document.querySelectorAll("[data-nav]").forEach(a => a.classList.toggle("active", a.dataset.nav === name));
  movePill();
}

// Scrolling down folds the tab bar's icons away and slides the top bar off; any scroll up (or the top of the page,
// or a new page) brings both back. One passive listener, read once per frame.
let lastScrollY = 0, scrollQueued = false;
function setCompact(on) {
  const bar = document.getElementById("tabs");
  document.querySelector(".top")?.classList.toggle("tucked", on);  // the top bar slides away with it
  if (bar && bar.classList.contains("compact") !== on) { bar.classList.toggle("compact", on); requestAnimationFrame(movePill); }
}
window.addEventListener("scroll", () => {
  if (scrollQueued) return;
  scrollQueued = true;
  requestAnimationFrame(() => {
    scrollQueued = false;
    const y = window.scrollY, dy = y - lastScrollY;
    if (y < 40) setCompact(false);
    else if (dy > 6) setCompact(true);
    else if (dy < -2) setCompact(false);
    lastScrollY = y;
  });
}, { passive: true });

// The tab bar's highlight is one pill that slides (with a little spring) to the active tab.
function movePill() {
  const bar = document.getElementById("tabs"), on = bar?.querySelector("a.active");
  let pill = bar?.querySelector(".tab-pill");
  if (!bar) return;
  if (!pill) { pill = document.createElement("span"); pill.className = "tab-pill"; bar.prepend(pill); }
  pill.classList.toggle("still", !motionOn() || !pill.dataset.placed);
  if (!on) { pill.style.opacity = "0"; return; }
  pill.style.opacity = "1";
  pill.style.width = `${on.offsetWidth}px`;
  pill.style.transform = `translateX(${on.offsetLeft}px)`;
  pill.dataset.placed = "1";
}
window.addEventListener("resize", () => movePill());

// Live pages ask again this often (s). The server answers from memory; the NHL's own scoreboard moves every ~20 s.
const LIVE_REFRESH = 10;

function autoRefresh(fn, seconds) {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => { if (!document.hidden) fn(true); else autoRefresh(fn, seconds); }, seconds * 1000);
}

const failed = e => `<div class="notice error">${esc(e.detail || "Couldn't load that. The NHL's data may be down; try again in a minute.")}</div>`;

async function standings(league = "nhl") {
  // One request shared by everyone asking at once; after 10 minutes the copy refreshes in the background.
  const hit = STANDINGS[league];
  const load = () => api(`/api/standings?league=${league}`);
  if (!hit) {
    const p = load().catch(e => { delete STANDINGS[league]; throw e; });
    STANDINGS[league] = { at: Date.now(), p };
    return p;
  }
  if (Date.now() - hit.at > 10 * 60000 && !hit.busy) {
    hit.busy = true;
    load().then(d => { STANDINGS[league] = { at: Date.now(), p: Promise.resolve(d) }; }).catch(() => { hit.busy = false; });
  }
  return hit.p;
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
  document.querySelector(".top-link[data-nav=settings]")?.classList.toggle("has-new", unseenChanges().length > 0);
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
    BANNER = "";
    await markChangesSeen();
  });
}

const KIND_NAME = { new: "New", improved: "Improved", fixed: "Fixed" };

function whatsNewView() {
  setNav("settings");
  const fresh = new Set(unseenChanges().map(c => c.id));
  const days = CHANGES.reduce((m, c) => ((m[c.date] ||= []).push(c), m), {});
  view.innerHTML = `${backLink("#/settings", "Settings")}<h1>What's new</h1>
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
  let kicker = "No games scheduled", right = "", acts = "";
  const hide = spoilerHidden(g);
  if (g) {
    const today = g.date === myTeams.data?.date;
    if (hide) {
      kicker = "Spoiler-free";
      right = `<b class="hero-sc">🙈</b><span>Score hidden</span>`;
      acts = spoilButton("peek", g, "Show score") + spoilButton("seen", g, "I've seen it");
    } else if (g.state === "live") {
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
    if (!hide && today && g.state !== "final" && g.state !== "postponed") {
      acts = spoilerMarked(g) ? `<span class="chip">🙈 Spoiler-free on</span>` : spoilButton("later", g, "🙈 Watching later");
    }
  }
  const w = g && g.state !== "final" ? g.watch : null;
  const wl = w?.links?.[0];
  const wtext = w && (w.network || w.app) ? `${esc(wl ? wl.name : w.network || w.app)}${wl ? " ↗" : ""}${w.have === true ? " · you have it" : w.have === false ? " · not in your services" : ""}` : "";
  const watch = !wtext ? "" : wl ? `<a class="chip strong" href="${esc(wl.url)}" target="_blank" rel="noopener">${wtext}</a>` : `<span class="chip strong">${wtext}</span>`;
  const st = c.standing;
  const chips = hide ? watch : [watch,
    st?.place ? `<span class="chip">${esc(st.place)}</span>` : "",
    c.record ? `<span class="chip">${esc(c.record)}${st?.pts != null ? ` · ${st.pts} pts` : ""}</span>` : "",
    streakText(c.streak) ? `<span class="chip">${esc(streakText(c.streak))}</span>` : "",
    st?.race ? `<span class="chip">${esc(st.race)}</span>` : ""].join("");
  const lastIsThis = c.last && g && c.last.id === g.id;
  const lines = hide ? "" : [
    c.week && c.week.games ? `<div><b>Last 7 days</b> ${esc(c.week.record)} · ${c.week.gf} goals for, ${c.week.ga} against</div>` : "",
    c.last && !lastIsThis ? `<div><b>Last</b> ${RESULT_WORD[c.last.code]} ${c.last.us}–${c.last.them} ${c.last.home ? "vs" : "at"} ${esc(teamName(c.last.opp))}</div>` : "",
    g?.watching?.length && g.state !== "final" ? `<div>👀 ${esc(namesList(g.watching))} watching</div>` : "",
    c.milestones?.length ? c.milestones.map(m => `<div>🎯 ${esc(m.text)}</div>`).join("") : "",
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
    ${acts ? `<div class="hero-acts">${acts}</div>` : ""}
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
  return `<div class="heroes${cards.length > 1 ? " many" : ""}">${cards.map(c => heroCard(c, live(c))).join("")}</div>`
    + (cards.length > 1 ? `<div class="hero-dots" aria-hidden="true">${cards.map((_, i) => `<span${i ? "" : ' class="on"'}></span>`).join("")}</div>` : "");
}

async function tonightView(date, quiet = false) {
  setNav("tonight");
  if (!quiet) showLoading(`Loading games…`);
  const leagues = LEAGUE === "both" ? ["nhl", "pwhl"] : [LEAGUE];
  let days, mineData = null;
  try {
    // Both leagues: the NHL's date leads, so the PWHL slate is for the same day.
    const mine = date ? null : loadMyTeams();
    const again = () => tonightView(date, true);
    const first = await fast(`/api/games?league=${leagues[0]}${date ? `&date=${encodeURIComponent(date)}` : ""}`, again, quiet);
    days = [first];
    if (leagues[1]) days.push(await fast(`/api/games?league=${leagues[1]}&date=${encodeURIComponent(date || first.date)}`, again, quiet));
    mineData = await mine;
  } catch (e) {
    view.innerHTML = failed(e);
    return;
  }
  const fav = favs();
  const order = g => ({ live: 0, pre: 1, postponed: 2, final: 3 }[g.state] ?? 1);
  const section = (title, list) => list.length ? `<h2>${title}</h2><div class="card">${list.map(g => gameCard(g, fav)).join("")}</div>` : "";
  // Games of teams with a card up top aren't listed again below it.
  const carded = new Set(date ? [] : (mineData?.teams || []).filter(c => leagues.includes(c.league)).map(c => c.abbr));
  const slate = (day, league) => {
    const games = (day.games || []).filter(g => !carded.has(g.away.abbr) && !carded.has(g.home.abbr));
    const mine = games.filter(g => fav.has(g.away.abbr) || fav.has(g.home.abbr));
    const rest = games.filter(g => !mine.includes(g));
    rest.sort((x, y) => order(x) - order(y) || (x.start || "").localeCompare(y.start || ""));
    const head = leagues.length > 1 ? `<div class="league-head ${league}">${LEAGUE_NAME[league]}</div>` : "";
    if (!(day.games || []).length) return head + `<div class="empty">No ${LEAGUE_NAME[league]} games this day.</div>`;
    return head + section("Your teams", mine) + section(mine.length ? "Around the league" : "All games", rest);
  };
  const dates = days.map(d => d.date).filter(Boolean);
  const day = { date: days[0].date || dates[0],
    // Arrows step to the nearest day with a game in any shown league.
    prev: days.map(d => d.prev).filter(Boolean).sort().pop(), next: days.map(d => d.next).filter(Boolean).sort()[0] };
  view.innerHTML = `
    <div id="getapp">${BANNER}</div>
    ${heroes(mineData, leagues, days.flatMap(d => d.games || []))}
    ${(n => n ? `<div class="spoil-note">🙈 Spoiler-free: ${n} game${n > 1 ? "s" : ""} hidden. Open one to reveal it when you've watched.</div>` : "")(days.flatMap(d => d.games || []).filter(spoilerHidden).length)}
    <div class="daybar">
      ${day.prev ? `<a href="#/day/${day.prev}" aria-label="Previous day">←</a>` : "<span></span>"}
      <h1>${esc(day.date ? dayTitle(day.date) : "Games")}</h1>
      ${day.next ? `<a href="#/day/${day.next}" aria-label="Next day">→</a>` : "<span></span>"}
    </div>
    ${days.map((d, i) => slate(d, leagues[i])).join("")}`;
  // The dots under swipeable team cards follow the card in view.
  const strip = view.querySelector(".heroes.many");
  if (strip) strip.addEventListener("scroll", () => {
    const i = Math.round(strip.scrollLeft / (strip.firstElementChild.offsetWidth + 10));
    view.querySelectorAll(".hero-dots span").forEach((d, j) => d.classList.toggle("on", i === j));
  }, { passive: true });
  // One banner at a time: getting the app / alerts first, otherwise what's new.
  bindBanner();
  getAppBanner().then(html => {
    const next = html || newBanner(), box = document.getElementById("getapp");
    if (!box || next === BANNER) return;
    BANNER = next;
    box.innerHTML = next;
    bindBanner();
  });
  const all = days.flatMap(d => d.games || []);
  // Warm your team cards' game pages on the server, so tapping one opens straight away.
  if (!quiet) setTimeout(() => (mineData?.teams || []).forEach(c => {
    const g = all.find(x => x.away.abbr === c.abbr || x.home.abbr === c.abbr);
    if (g && g.state !== "postponed") fetch(g.league === "pwhl" ? `/api/pwhl/game/${g.id}` : `/api/game/${g.id}`).catch(() => {});
  }), 1500);
  if (all.some(g => g.state === "live" || (g.state === "pre" && Date.parse(g.start) - Date.now() < 30 * 60000))) {
    autoRefresh(q => tonightView(date, q), LIVE_REFRESH);
  }
}

// ---- Pick'em -----------------------------------------------------------------------------------
// Pick a winner for every game before puck drop. ★ = lock of the night: 2 points if right, nothing if wrong.
// Friends' picks show once a game starts. Scores follow spoiler-free like everywhere else.
async function pickemView(date, quiet = false) {
  setNav("picks");
  if (!quiet) showLoading(`Loading Pick'em…`);
  const leagues = LEAGUE === "both" ? ["nhl", "pwhl"] : [LEAGUE];
  let d, hidden;
  try {
    [d, hidden] = await Promise.all([
      fast(`/api/pickem?leagues=${leagues.join(",")}${date ? `&date=${encodeURIComponent(date)}` : ""}`, () => pickemView(date, true), quiet),
      hiddenToday().catch(() => [])]);
  } catch (e) { view.innerHTML = failed(e); return; }
  const code = abbr => TEAMS[abbr]?.code || abbr;
  const now = new Date().toISOString();
  const begun = g => g.state !== "pre" || (g.start && g.start <= now);
  const rows = d.games.map(g => {
    const hide = spoilerHidden(g), k = spKey(g), started = begun(g);
    SPOIL_GAMES.set(k, g);
    const done = g.state === "final" && !hide;
    const o = oddsOn() && !hide ? g.odds : null;
    const side = t => {
      const on = g.mine === t.abbr;
      const res = on && done && g.won != null ? (g.won ? " won" : " lost") : "";
      return `<button class="pk${on ? " on" : ""}${res}" data-pick="${t.abbr}" data-k="${esc(k)}" ${started ? "disabled" : ""}>${mark(t.abbr)}${!hide && g.state !== "pre" && t.score != null ? `<b class="pk-sc">${t.score}</b>` : `<span class="pk-nm">${esc(teamName(t.abbr))}</span>`}</button>`;
    };
    // Before puck drop: each team's win chance under its button, "2×" on the underdog while the upset bonus is on.
    const pct = t => {
      const dog = g.bonus && o.fav && o.fav !== t.abbr;
      return `<span class="${dog ? "dog" : ""}">${t === g.home ? o.home_pct : o.away_pct}%${dog ? " · 2× if right" : ""}</span>`;
    };
    const chances = o?.away_pct && !started ? `<div class="pick-odds">${pct(g.away)}<span></span>${pct(g.home)}</div>` : "";
    const mid = hide ? "🙈" : g.state === "live" ? `<span class="live">LIVE</span>` : g.state === "final" ? "Final"
      : g.state === "postponed" ? "Postponed" : g.start ? esc(time(g.start)) : "TBD";
    const friends = (g.picks || []).filter(p => !p.me);
    const upset = o?.upset && done ? `<div class="pick-friends"><span class="upset">⚡ Upset!</span>${g.won && g.pts > 1 ? ` You got <b>${g.pts} points</b>.` : ""}</div>` : "";
    return `<div class="pick-row">
      <div class="pick-line">${side(g.away)}<div class="pick-mid">${mid}</div>${side(g.home)}
        <button class="lockbtn${g.lock ? " on" : ""}" data-lockk="${esc(k)}" ${started ? "disabled" : ""} aria-pressed="${g.lock}" title="Lock of the night">★</button></div>
      ${chances}
      ${started && friends.length ? `<div class="pick-friends">${friends.map(p => `${esc(p.name)} ${esc(code(p.team))}${p.lock ? " ★" : ""}`).join(" · ")}</div>`
        : !started && g.count > (g.mine ? 1 : 0) ? `<div class="pick-friends">${g.count - (g.mine ? 1 : 0)} friend${g.count - (g.mine ? 1 : 0) > 1 ? "s have" : " has"} picked</div>` : ""}
      ${upset}
    </div>`;
  }).join("");
  const table = list => list.length ? `<div class="card"><table class="board"><tr><th></th><th>Name</th><th>Pts</th><th>Right–wrong</th></tr>
    ${list.map((r, i) => `<tr class="${r.me ? "me" : ""}"><td class="muted">${i + 1}</td><td>${esc(r.name)}${r.me ? " (you)" : ""}</td><td><b>${r.pts}</b></td><td>${r.w}–${r.l}${r.upsets ? ` <span class="muted">· ⚡${r.upsets}</span>` : ""}</td></tr>`).join("")}</table></div>`
    : `<div class="card"><div class="empty">No results yet. Make some picks!</div></div>`;
  const b = d.board, last = b.last?.table || [];
  const best = last[0], meLast = last.find(r => r.me);
  const lastLine = best ? `<div class="card pad small"><b>${esc(shortDate(b.last.date))}</b>: ${esc(best.name)} went ${best.w} for ${best.w + best.l}${meLast && meLast !== best ? `, you went ${meLast.w} for ${meLast.w + meLast.l}` : ""}.</div>` : "";
  const hid = hidden.filter(g => g.state === "final" && leagues.includes(g.league === "pwhl" ? "pwhl" : leagueOf(g.home.abbr)));
  view.innerHTML = `
    <div class="daybar">
      ${d.prev ? `<a href="#/picks/${d.prev}" aria-label="Previous day">←</a>` : "<span></span>"}
      <h1>${esc(dayTitle(d.date))}</h1>
      ${d.next ? `<a href="#/picks/${d.next}" aria-label="Next day">→</a>` : "<span></span>"}
    </div>
    <p class="help">Tap who wins: <b>1 point</b> for every one you get right${d.games.some(g => g.bonus) ? `, or <b>2 points</b> if they win as the underdog (marked <b>2×</b>)` : ""}. Tap ★ on one game a night to make it your lock: it <b>doubles</b> that game's points (nothing if it's wrong). Picks lock at puck drop.</p>
    ${rows ? `<div class="card picks">${rows}</div>` : `<div class="empty">No games this day.</div>`}
    ${hid.length ? `<h2>The table</h2>${spoilCover(hid, "The Pick'em table")}` : `
      ${lastLine ? `<h2>Last results</h2>${lastLine}` : ""}
      <h2>This week</h2>${table(b.week)}
      <h2>Season ${esc(b.season)}${leagues.length > 1 ? "" : ` · ${LEAGUE_NAME[leagues[0]]}`}</h2>${table(b.table)}`}
    <p class="help">You show up as <b>${esc(d.name)}</b>. <a href="#/settings">Change your name in Settings</a>.</p>`;
  const send = async (g, team, lock) => {
    try {
      await api("/api/pickem", { method: "POST", body: JSON.stringify({ league: g.league === "pwhl" ? "pwhl" : "nhl", id: g.id, date: g.date, team, lock }) });
    } catch (e) { toast(e.detail || "Couldn't save that pick. Try again.", true); }
    pickemView(date, true);
  };
  view.querySelectorAll("[data-pick]").forEach(btn => btn.addEventListener("click", () => {
    const g = SPOIL_GAMES.get(btn.dataset.k);
    const team = g.mine === btn.dataset.pick ? null : btn.dataset.pick;  // tap your pick again to clear it
    btn.closest(".pick-line").querySelectorAll(".pk").forEach(x => x.classList.toggle("on", x === btn && !!team));
    send(g, team, team ? g.lock : false);
  }));
  view.querySelectorAll("[data-lockk]").forEach(btn => btn.addEventListener("click", () => {
    const g = SPOIL_GAMES.get(btn.dataset.lockk);
    if (!g.mine) { toast("Pick a team for this game first", true); return; }
    view.querySelectorAll(".lockbtn").forEach(x => x.classList.toggle("on", x === btn && !g.lock));
    send(g, g.mine, !g.lock);
  }));
  if (d.games.some(g => g.state === "live" || (g.state === "pre" && Date.parse(g.start) - Date.now() < 30 * 60000))) {
    autoRefresh(q => pickemView(date, q), 30);
  }
}

// ---- getting the app + alerts --------------------------------------------------------------
// Tonight's one banner slot: getting the app / alerts first, otherwise what's new. BANNER is the last one shown, so a
// re-render paints it straight away instead of blanking the slot and shifting the page while it's re-checked.
let BANNER = "";
function bindBanner() {
  const box = document.getElementById("getapp");
  box?.querySelector(".getapp .x")?.addEventListener("click", () => {
    try { localStorage.setItem("getappHidden", "1"); } catch { /* fine */ }
    BANNER = "";
    box.innerHTML = "";
  });
  bindNewBanner();
}

async function getAppBanner() {
  let hidden = false;
  try { hidden = localStorage.getItem("getappHidden") === "1"; } catch { /* fine */ }
  if (hidden) return "";
  let text = null;
  if (!isStandalone() && device() !== "desktop") {
    text = "<b>Put Shots on Goal on your home screen</b> and get alerts when your teams score.";
  } else if ("PushManager" in window && Notification.permission === "default") {
    const reg = await navigator.serviceWorker?.ready.catch(() => null);
    const sub = reg ? await reg.pushManager.getSubscription().catch(() => null) : null;
    if (!sub) text = "<b>Turn on alerts</b> for puck drop, goals and finals for your teams.";
  }
  return text ? `<div class="getapp"><div>${text}</div><a class="btn primary small" href="#/app">Show me how</a>
    <button class="x" aria-label="Hide">×</button></div>` : "";
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
  view.innerHTML = `${backLink("#/settings", "Settings")}
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

// Before puck drop: the matchup (sog/nhl.py parse_preview). It goes away once the game starts.
const RES_WORD = { W: "Win", L: "Loss", OT: "OT/SO loss" };
// Two teams in near-identical colours (Sabres and Leafs are both navy) would read as one bar: grey out the away side.
function apart(ac, hc) {
  const rgb = c => /^#[0-9a-f]{6}$/i.test(c) ? [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16)) : null;
  const x = rgb(ac), y = rgb(hc);
  return x && y && Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]) < 80 ? "var(--muted)" : ac;
}
function previewBlock(p, a, h, ac, hc) {
  ac = apart(ac, hc);
  const side = (s, abbr) => {
    const f = p.form[s] || {}, pl = p.places?.[s];
    const dots = [...(f.last || [])].reverse().map(r => `<i class="res-${r.res}" title="${esc(RES_WORD[r.res])} vs ${esc(r.opp)}"></i>`).join("");
    const bits = [f.record, pl?.div_rank ? `${ordinal(pl.div_rank)} in ${pl.div}` : "", f.streak ? `streak ${f.streak}` : ""].filter(Boolean);
    return `<div class="form-row">${mark(abbr)}<div><div class="who">${esc(teamName(abbr))}</div><div class="detail">${esc(bits.join(" · "))}</div></div>
      ${dots ? `<div class="dots" aria-label="Recent results, oldest first">${dots}</div>` : ""}</div>`;
  };
  let out = `<h2>Matchup</h2><div class="card">${side("away", a)}${side("home", h)}
    <div class="pre-note">Recent results, oldest to newest: <i class="res-W"></i> win <i class="res-OT"></i> OT/SO loss <i class="res-L"></i> loss</div></div>`;

  if (p.stats.length) {
    // The better side is bold; the bar fills toward it (lower is better for goals against).
    const row = s => {
      const na = parseFloat(s.away), nh = parseFloat(s.home);
      const [wa, wh] = s.low ? [nh, na] : [na, nh], total = wa + wh || 1;
      const better = na === nh ? null : (na > nh) !== s.low ? "away" : "home";
      const val = (v, r, me) => `<span class="v${better === me ? " best" : ""}">${esc(v)}${r ? `<small>${esc(ordinal(r))}</small>` : ""}</span>`;
      return `<div class="cmp">${val(s.away, s.away_rank, "away")}
        <div><div class="lbl">${esc(s.label)}</div><div class="bar"><i style="width:${wa / total * 100}%;background:${ac}"></i><i style="width:${wh / total * 100}%;background:${hc}"></i></div></div>
        ${val(s.home, s.home_rank, "home")}</div>`;
    };
    out += `<h2>Season so far</h2><div class="card compare pre">
      <div class="cmp"><span>${mark(a)}</span><span class="muted small" style="text-align:center">League rank under each number</span><span style="text-align:right">${mark(h)}</span></div>
      ${p.stats.map(row).join("")}</div>`;
  }

  if (p.hot.length) {
    const who = x => x ? `<div><div class="who">${esc(x.name)} <span class="muted small">${esc(x.pos || "")}</span></div><div class="big-num">${x.value}</div></div>` : "<div></div>";
    out += `<h2>Who's hot · ${esc(p.hot_context)}</h2><div class="card">${p.hot.map(r =>
      `<div class="hot-row">${who(r.away)}<div class="lbl">${esc(r.label)}</div>${who(r.home)}</div>`).join("")}</div>`;
  }

  if (p.goalies.away.length || p.goalies.home.length) {
    const gl = (s, abbr) => p.goalies[s].map(x => `<div class="event g-row">${mark(abbr)}<div><div class="who">${esc(x.name)} <span class="muted small">#${x.number ?? ""}</span></div>
      <div class="detail">${esc(x.record || "")} · ${x.sv != null ? x.sv.toFixed(3).replace(/^0/, "") : "–"} SV% · ${x.gaa != null ? x.gaa.toFixed(2) : "–"} GAA${x.so ? ` · ${x.so} SO` : ""} · ${x.gp} GP</div></div></div>`).join("");
    out += `<h2>Goalies this season</h2><div class="card">${gl("away", a)}${gl("home", h)}</div>
      <p class="help">The NHL doesn't name starting goalies ahead of time. These are each team's goalies this season, most games first.</p>`;
  }

  const ser = p.series, done = ser.games.filter(x => x.state === "final"), next = ser.games.filter(x => x.state === "pre");
  const lead = ser.away_wins === ser.home_wins ? (done.length ? `Series tied ${ser.away_wins}–${ser.home_wins}` : "First meeting this season")
    : `${teamName(ser.away_wins > ser.home_wins ? a : h)} lead the season series ${Math.max(ser.away_wins, ser.home_wins)}–${Math.min(ser.away_wins, ser.home_wins)}`;
  out += `<h2>Season series</h2><div class="card pad small"><b>${esc(lead)}</b>
    ${done.map(x => `<div class="detail">${esc(shortDate(x.date))}: ${esc(x.away)} ${x.away_score}, ${esc(x.home)} ${x.home_score}${x.outcome && x.outcome !== "REG" ? ` (${esc(x.outcome)})` : ""}</div>`).join("")}
    ${next.length ? `<div class="detail">Still to come: ${next.map(x => `${esc(shortDate(x.date))}, ${esc(x.away)} at ${esc(x.home)}`).join(" · ")}</div>` : ""}
  </div>`;

  const ppl = p.people || {}, coach = ["away", "home"].filter(s => ppl[s]?.coach).map(s => `${esc(teamName(s === "away" ? a : h))}: ${esc(ppl[s].coach)}`);
  const scr = ["away", "home"].filter(s => ppl[s]?.scratches?.length).map(s => `${esc(teamName(s === "away" ? a : h))}: ${esc(ppl[s].scratches.join(", "))}`);
  if (coach.length || scr.length) out += `<p class="help">${coach.length ? `Coaches · ${coach.join(" · ")}` : ""}${scr.length ? `<br>Scratches · ${scr.join(" · ")}` : ""}</p>`;
  return out;
}

let moreStatsOpen = false;  // stays open across the live refresh
async function gameView(id, quiet = false, league = "nhl") {
  setNav("tonight");
  if (!quiet) showLoading(`Loading game…`);
  let d;
  const path = league === "pwhl" ? `/api/pwhl/game/${encodeURIComponent(id)}` : `/api/game/${encodeURIComponent(id)}`;
  try { d = await fast(path, () => gameView(id, true, league), quiet); } catch (e) { view.innerHTML = failed(e); return; }
  const g = d.game, a = g.away.abbr, h = g.home.abbr;
  if (league === "pwhl") g.league = "pwhl";
  if (spoilerHidden(g)) {
    view.innerHTML = `${backLink("#/")}<div class="card pad spoil-cover">
      <div class="spoil-teams">${mark(a, true)}<span>vs</span>${mark(h, true)}</div>
      <div class="spoil-eye">🙈</div>
      <p><b>${esc(fullName(a))} vs ${esc(fullName(h))}</b> is hidden. Scores, goals, the shot map and the recap stay
        out of sight until you've watched it.</p>
      <div class="links" style="justify-content:center">${spoilButton("peek", g, "Show it now")}${spoilButton("seen", g, "I've seen it", true)}</div>
      ${g.state === "live" ? `<div style="padding-top:6px">${watchLine(g.watch, g)}</div>` : ""}
    </div>`;
    return;
  }
  const ac = TEAMS[a]?.color || "#888", hc = TEAMS[h]?.color || "#888";
  let state = "";
  if (g.state === "live") state = `<span class="live">LIVE</span> ${esc(g.intermission ? `${g.period} intermission` : `${g.period} · ${g.clock || ""}`)}`;
  else if (g.state === "final") state = `Final${g.outcome && g.outcome !== "REG" ? ` (${esc(g.outcome)})` : ""}`;
  else if (g.state === "postponed") state = "Postponed";
  else state = g.start ? `${esc(shortDate(g.date))} · ${esc(time(g.start))}` : "Time TBD";
  const showScore = g.state === "live" || g.state === "final";
  // Friends: who's watching, rivalries and reactions (sog/social.py).
  const S = d.social || { watching: [], reactions: {}, mine: {}, rivals: [], emoji: [] };
  const others = S.watching.filter(w => !w.me);
  const friendsLine = [
    others.length ? `👀 ${esc(namesList(others))} ${g.state === "final" ? "watched" : others.length > 1 ? "are watching" : "is watching"}` : "",
    S.rivals.length ? `⚔️ Rivalry: ${S.rivals.map(r => `${esc(r.name)}'s ${esc(teamName(r.team))}`).join(", ")}` : ""].filter(Boolean).join(" · ");
  const canReact = g.state === "live" || g.state === "final";
  const rx = key => {
    if (!canReact) return "";
    key = key.slice(0, 82);
    const counts = S.reactions[key] || {}, mine = S.mine[key];
    const chips = Object.entries(counts).map(([e, n]) => `<button class="rxc${mine === e ? " mine" : ""}" data-rx="${e}" data-ev="${esc(key)}">${e} ${n}</button>`).join("");
    return `<div class="rxs">${chips}<button class="rxc add" data-rxopen="${esc(key)}" aria-label="React">${chips ? "＋" : "🙂＋"}</button></div>`;
  };
  const side = (t, abbr) => `<a class="side" href="#/team/${abbr}">${mark(abbr, true)}<span class="nm">${esc(t.name || teamName(abbr))}</span></a>`;

  // Top card in three groups: the game itself, where to watch it, and you + friends (watching now or later).
  // On touch screens the buttons sit on the side of the hand picked in Settings > Display; elsewhere they're centred.
  const upcoming = g.state !== "final" && g.state !== "postponed";
  const sit = d.situation && g.state === "live" && !g.intermission ? `<div class="sitpill">${esc(d.situation.text)}</div>` : "";
  const report = g.state !== "final" && league !== "pwhl" ? `<button class="linkish" id="report">Wrong channel?</button>` : "";
  const social = upcoming || friendsLine ? `<div class="gsec gsec-row">
      ${upcoming ? `<button class="btn small${S.me_watching ? " primary" : ""}" id="watching">${S.me_watching ? "👀 You're watching" : "👀 I'm watching"}</button>
        ${spoilerMarked(g) ? spoilButton("seen", g, "🙈 Spoiler-free on · turn off") : spoilButton("later", g, "🙈 Watching later")}` : ""}
      ${friendsLine ? `<span class="gsec-note">${friendsLine}</span>` : ""}</div>` : "";

  let html = `${backLink("#/")}<div class="card">
    <div class="scorebug">
      ${side(g.away, a)}
      <div><div class="score">${showScore ? `${g.away.score ?? 0} – ${g.home.score ?? 0}` : "vs"}</div><div class="state">${state}</div>${sit}</div>
      ${side(g.home, h)}
    </div>
    ${watchBlock(g, report)}
    ${league === "pwhl" ? "" : oddsBlock(g, ac, hc)}
    ${social}
  </div>
  ${d.recap ? `<p class="recap">${esc(d.recap)}</p>` : ""}`;

  if (g.state === "pre" && d.preview) html += previewBlock(d.preview, a, h, ac, hc);

  const goals = d.scoring.filter(p => p.goals.length);
  if (goals.length) {
    html += `<h2>Scoring</h2><div class="card">${goals.map(p => `<div class="subhead">${esc(p.period)}</div>${p.goals.map(x => {
      const tags = [x.strength !== "EV" ? x.strength : "", x.modifier === "empty-net" ? "EN" : ""].filter(Boolean)
        .map(t => `<span class="tag">${esc(t)}</span>`).join("");
      const assists = x.assists.length ? x.assists.map(y => `${plink(y.name, y.pid, league)}${y.total ? ` (${y.total})` : ""}`).join(", ") : "Unassisted";
      return `<div class="event"><span class="when">${esc(x.time)}</span>${mark(x.team)}
        <div><span class="run">${x.away}–${x.home}</span><div class="who">${plink(x.scorer, x.pid, league)}${x.total ? ` (${x.total})` : ""}${tags}</div>
        <div class="detail">${assists}${x.clip ? ` · <a href="${esc(x.clip)}" target="_blank" rel="noopener">clip</a>` : ""}</div>${rx(`g:${p.period}-${x.time}-${x.scorer}`)}</div></div>`;
    }).join("")}`).join("")}</div>`;
  }

  if (d.shotmap?.length) html += shotMap(d.shotmap, a, h) + momentumCard(d.shotmap, a, h, ac, hc, league);

  if (d.linescore.length) {
    const shots = Object.fromEntries(d.shots.map(s => [s.period, s]));
    html += `<h2>By period</h2><div class="card scroll"><table>
      <tr><th></th>${d.linescore.map(p => `<th>${esc(p.period)}</th>`).join("")}<th>T</th><th>SOG</th></tr>
      ${["away", "home"].map(s => `<tr><td class="team"><span class="tm">${mark(s === "away" ? a : h)}</span></td>
        ${d.linescore.map(p => `<td>${p[s] ?? ""}<span class="muted small">${shots[p.period] ? ` · ${shots[p.period][s]}` : ""}</span></td>`).join("")}
        <td><b>${g[s].score ?? 0}</b></td><td>${g[s].sog ?? ""}</td></tr>`).join("")}
    </table></div><p class="help">Goals · shots in each period.</p>`;
  }


  if (d.stars.length) {
    html += `<h2>Three stars</h2><div class="card">${d.stars.map(s => `<div class="event star"><span class="when">${"★".repeat(s.star)}</span>${mark(s.team)}
      <div class="star-who">${photo(league, s.team, s.pid, 40)}<div><div class="who">${plink(s.name, s.pid, league)} <span class="muted small">${esc(s.pos)}</span></div><div class="detail">${esc(s.line)}</div></div></div></div>`).join("")}</div>`;
  }

  // Team stats, penalties and players: one tap away so the page leads with what happened.
  let more = "";
  if (d.team_stats.length) {
    more += `<h2>Team stats</h2><div class="card compare">
      <div class="cmp"><span>${mark(a)}</span><span></span><span style="text-align:right">${mark(h)}</span></div>
      ${d.team_stats.map(s => compareRow(s.label, s.away, s.home, ac, hc)).join("")}</div>`;
  }

  const pens = d.penalties.filter(p => p.items.length);
  if (pens.length) {
    more += `<h2>Penalties</h2><div class="card">${pens.map(p => `<div class="subhead">${esc(p.period)}</div>${p.items.map(x =>
      `<div class="event"><span class="when">${esc(x.time)}</span>${mark(x.team)}<div><div class="who">${esc(x.player || "Bench")}</div>
      <div class="detail">${esc(x.desc)} · ${x.minutes} min</div>${rx(`p:${p.period}-${x.time}-${x.player || "Bench"}`)}</div></div>`).join("")}`).join("")}</div>`;
  }

  for (const s of ["away", "home"]) {
    const p = d.players[s];
    if (!p || !p.skaters.length) continue;
    const abbr = s === "away" ? a : h;
    more += `<h2>${esc(teamName(abbr))} players</h2><div class="card scroll"><table>
      <tr><th>Skater</th><th>G</th><th>A</th><th>P</th><th>+/-</th><th>SOG</th><th>Hits</th><th>TOI</th></tr>
      ${p.skaters.map(x => `<tr><td>${plink(x.name, x.pid, league)} <span class="muted small">${esc(x.pos)}</span></td><td>${x.g}</td><td>${x.a}</td><td><b>${x.p}</b></td><td>${x.pm > 0 ? "+" : ""}${x.pm}</td><td>${x.sog}</td><td>${x.hits}</td><td>${esc(x.toi || "")}</td></tr>`).join("")}
    </table>${p.goalies.length ? `<table><tr><th>Goalie</th><th>Saves</th><th>GA</th><th>SV%</th><th>TOI</th></tr>
      ${p.goalies.map(x => `<tr><td>${plink(x.name, x.pid, league)}</td><td>${x.saves}/${x.sa}</td><td>${x.ga}</td><td>${x.sa ? (x.saves / x.sa).toFixed(3).replace(/^0/, "") : "–"}</td><td>${esc(x.toi || "")}</td></tr>`).join("")}</table>` : ""}</div>`;
  }

  if (more) html += `<details class="more-stats" ${moreStatsOpen ? "open" : ""}><summary>More stats: team, penalties, players</summary>${more}</details>`;

  if (g.venue) html += `<p class="help" style="text-align:center;margin-top:18px">${esc(g.venue)}</p>`;
  view.innerHTML = html;
  view.querySelector(".more-stats")?.addEventListener("toggle", e => { moreStatsOpen = e.target.open; });
  document.getElementById("report")?.addEventListener("click", async e => {
    const note = prompt(`We said: ${g.watch?.app || "no channel"} (${g.watch?.why || ""}).\nWhere is it actually on? (optional)`);
    if (note === null) return;
    e.target.disabled = true;
    try { await api("/api/report", { method: "POST", body: JSON.stringify({ game_id: g.id, note }) }); e.target.textContent = "Thanks, reported."; }
    catch { e.target.textContent = "Couldn't send that. Try again."; e.target.disabled = false; }
  });
  const post = async (path, body) => {
    try { await api(path, { method: "POST", body: JSON.stringify({ league: league === "pwhl" ? "pwhl" : "nhl", id: g.id, date: g.date, ...body }) }); }
    catch (e) { toast(e.detail || "Couldn't save that. Try again.", true); }
    gameView(id, true, league);
  };
  document.getElementById("watching")?.addEventListener("click", () => post("/api/watching", { on: !S.me_watching }));
  view.querySelectorAll("[data-rxopen]").forEach(b => b.addEventListener("click", () => {
    const key = b.dataset.rxopen, mine = S.mine[key];
    b.parentElement.innerHTML = S.emoji.map(e => `<button class="rxc pick${mine === e ? " mine" : ""}" data-rx="${e}" data-ev="${esc(key)}">${e}</button>`).join("");
    bindRx();
  }));
  const bindRx = () => view.querySelectorAll("[data-rx]").forEach(b => b.onclick = () =>
    post("/api/react", { event: b.dataset.ev, emoji: S.mine[b.dataset.ev] === b.dataset.rx ? null : b.dataset.rx }));
  bindRx();
  view.querySelectorAll("[data-shots]").forEach(b => b.addEventListener("click", () => {
    view.querySelectorAll("[data-shots]").forEach(x => x.classList.toggle("on", x === b));
    view.querySelectorAll(".rink [data-p]").forEach(dot => { dot.style.display = b.dataset.shots === "all" || dot.dataset.p === b.dataset.shots ? "" : "none"; });
  }));
  if (g.state === "live" || (g.state === "pre" && Date.parse(g.start) - Date.now() < 30 * 60000)) autoRefresh(q => gameView(id, q, league), LIVE_REFRESH);
}

// ---- Wire ----------------------------------------------------------------------------
const WIRE_KINDS = [["", "All"], ["move", "Moves"], ["news", "News"], ["insider", "Insiders"]];

function linkify(text) {
  return esc(text).replace(/https?:\/\/[^\s<]+/g, u => `<a href="${u}" target="_blank" rel="noopener">${u.replace(/^https?:\/\//, "").slice(0, 40)}…</a>`);
}

function wireItem(i, fav, hidden = []) {
  const isFav = i.teams.some(t => fav.has(t));
  const spoils = hidden.find(g => (i.teams.includes(g.away.abbr) || i.teams.includes(g.home.abbr)) && (i.time || "") >= (g.start || ""));
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
  if (spoils) {
    return `<div class="witem${isFav ? " fav" : ""} spoil">${head}<button class="linkish" data-unspoil>🙈 Hidden: might spoil ${esc(vsLine(spoils))}. Tap to show.</button><div class="spoil-body">${body}</div></div>`;
  }
  return `<div class="witem${isFav ? " fav" : ""}">${head}${body}</div>`;
}

async function wireView(quiet = false) {
  setNav("wire");
  let state = { kind: "", mine: false };
  try { state = { ...state, ...JSON.parse(localStorage.getItem("wire") || "{}") }; } catch { /* defaults */ }
  if (!quiet) showLoading(`Loading the Wire…`);
  const leagues = LEAGUE === "both" ? ["nhl", "pwhl"] : [LEAGUE];
  let lists, hidden;
  try {
    [hidden, ...lists] = await Promise.all([hiddenToday().catch(() => []),
      ...leagues.map(l => fast(`/api/wire?league=${l}&kind=${state.kind}&mine=${state.mine ? 1 : 0}`, () => wireView(true), quiet))]);
  } catch (e) { view.innerHTML = failed(e); return; }
  const fav = favs();
  const block = (items, l) => (leagues.length > 1 ? `<div class="league-head ${l}">${LEAGUE_NAME[l]}</div>` : "") +
    (items.length ? `<div class="card">${items.slice(0, leagues.length > 1 ? 40 : 150).map(i => wireItem(i, fav, hidden)).join("")}</div>`
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

// ---- momentum and shot quality ------------------------------------------------------------------------
// Both come from the shot map's x/y (home shoots right, nets at x = ±89), so they cost no extra request.
const PERIOD_ORDER = ["1st", "2nd", "3rd", "OT", "2OT", "3OT", "4OT"];
function xgOf(s, home) {
  const net = s.team === home ? 89 : -89;
  const dx = Math.max(Math.abs(net - s.x), 1), dy = Math.abs(s.y);
  const dist = Math.hypot(dx, dy), angle = Math.atan2(dy, dx) * 180 / Math.PI;
  return 1 / (1 + Math.exp(-(-0.69 - 0.058 * dist - 0.012 * angle)));  // ~22% from the slot, ~1.5% from the blue line
}
function momentumCard(shots, a, h, ac, hc, league) {
  const live = shots.filter(s => PERIOD_ORDER.includes(s.period));
  if (live.length < 4) return "";
  const periods = PERIOD_ORDER.filter(p => live.some(s => s.period === p));
  // 5-minute chunks: four per regulation period, one for each overtime.
  const chunks = periods.flatMap(p => p.endsWith("OT") ? [[p, 0]] : [0, 1, 2, 3].map(i => [p, i]));
  const idx = s => { const m = parseInt(String(s.time || "0").split(":")[0], 10) || 0;
    return chunks.findIndex(([p, i]) => p === s.period && (p.endsWith("OT") || i === Math.min(3, Math.floor(m / 5)))); };
  const count = chunks.map(() => ({ [a]: 0, [h]: 0, ga: 0, gh: 0 }));
  for (const s of live) { const c = count[idx(s)]; if (!c) continue; c[s.team] = (c[s.team] || 0) + 1; if (s.kind === "goal") c[s.team === h ? "gh" : "ga"]++; }
  const max = Math.max(1, ...count.map(c => Math.max(c[a], c[h])));
  const W = 320, mid = 62, scale = 50 / max, bw = (W - 30) / chunks.length;
  const bars = count.map((c, i) => {
    const x = 26 + i * bw, w = Math.max(2, bw - 3);
    const goal = (n, y) => n ? `<circle cx="${(x + w / 2).toFixed(1)}" cy="${y}" r="3.2" fill="var(--text)"/>` : "";
    return `<rect x="${x.toFixed(1)}" y="${(mid - c[h] * scale).toFixed(1)}" width="${w.toFixed(1)}" height="${(c[h] * scale).toFixed(1)}" rx="1.5" fill="${hc}"/>
      <rect x="${x.toFixed(1)}" y="${mid}" width="${w.toFixed(1)}" height="${(c[a] * scale).toFixed(1)}" rx="1.5" fill="${ac}"/>
      ${goal(c.gh, (mid - c[h] * scale - 6).toFixed(1))}${goal(c.ga, (mid + c[a] * scale + 6).toFixed(1))}`;
  }).join("");
  const labels = periods.map(p => { const first = chunks.findIndex(([q]) => q === p), n = chunks.filter(([q]) => q === p).length;
    return `<text x="${(26 + (first + n / 2) * bw).toFixed(1)}" y="134" text-anchor="middle">${esc(p)}</text>`; }).join("");
  const dividers = periods.slice(1).map(p => { const x = 26 + chunks.findIndex(([q]) => q === p) * bw - 1.5;
    return `<line x1="${x.toFixed(1)}" y1="6" x2="${x.toFixed(1)}" y2="120" stroke="var(--border)" stroke-dasharray="3 3"/>`; }).join("");
  const xg = t => live.filter(s => s.team === t).reduce((n, s) => n + xgOf(s, h), 0);
  return `<h2>Momentum</h2><div class="card pad">
    <svg class="momentum" viewBox="0 0 ${W} 140" role="img" aria-label="Shot attempts every five minutes: ${esc(teamName(h))} above the line, ${esc(teamName(a))} below">
      <line x1="24" y1="${mid}" x2="${W}" y2="${mid}" stroke="var(--border)"/>${dividers}${bars}
      <text x="0" y="30">${esc(TEAMS[h]?.code || h)}</text><text x="0" y="100">${esc(TEAMS[a]?.code || a)}</text>${labels}
    </svg>
    <div class="xg"><span>${mark(a)} <b>${xg(a).toFixed(1)}</b></span><span class="muted small">Shot quality (expected goals)</span><span><b>${xg(h).toFixed(1)}</b> ${mark(h)}</span></div>
    <p class="help" style="margin:8px 0 0">Bars: ${league === "pwhl" ? "shots on goal" : "shots on goal and misses"} every 5 minutes; dots are goals.
      Expected goals adds up how likely each shot was to go in, from its distance and angle. A rough estimate by this app.</p>
  </div>`;
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

// Your teams as shortcuts above the standings; every team name in the tables opens its page too.
function yourTeamTiles(lg) {
  const mine = [...favs()].filter(a => leagueOf(a) === lg);
  return mine.length ? `<div class="grid tiles-top">${mine.map(a => `<a class="tile" href="#/team/${a}">${mark(a)}${esc(teamName(a))}</a>`).join("")}</div>` : "";
}

async function standingsView(mode = "division") {
  setNav("league");
  showLoading(`Loading standings…`);
  const lg = pageLeague();
  standings(lg).catch(() => null);  // start loading the table while the spoiler check runs
  const hid = (await hiddenToday().catch(() => [])).filter(g => g.state === "final" && leagueOf(g.home.abbr) === lg);
  if (hid.length) {
    view.innerHTML = leagueTabs("standings") + leaguePicker(lg) + spoilCover(hid, "These standings", "include");
    bindLeaguePicker(() => standingsView(mode));
    return;
  }
  if (lg === "pwhl") {
    let rows;
    try { rows = await standings("pwhl"); } catch (e) { view.innerHTML = failed(e); return; }
    view.innerHTML = leagueTabs("standings") + leaguePicker("pwhl") + yourTeamTiles("pwhl") + pwhlStandings(rows);
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
  view.innerHTML = `${leagueTabs("standings")}${leaguePicker("nhl")}${yourTeamTiles("nhl")}<div class="seg">${STANDING_MODES.map(([k, l]) => `<button data-mode="${k}" class="${k === mode ? "on" : ""}">${l}</button>`).join("")}</div>${body}`;
  bindLeaguePicker(() => standingsView(mode));
  view.querySelectorAll("[data-mode]").forEach(b => b.addEventListener("click", () => {
    try { localStorage.setItem("standingsMode", b.dataset.mode); } catch { /* fine */ }
    standingsView(b.dataset.mode);
  }));
}

const MS_WORD = { goals: ["goal", "goals"], assists: ["assist", "assists"], points: ["point", "points"], gp: ["game", "games"],
  wins: ["win", "wins"], shutouts: ["shutout", "shutouts"] };

async function teamView(abbr) {
  setNav("league");
  showLoading(`Loading ${esc(fullName(abbr))}…`);
  let d, rows = [];
  let hidden = [];
  try { [d, rows, hidden] = await Promise.all([fast(`/api/team/${encodeURIComponent(abbr)}`, () => teamView(abbr)), standings(leagueOf(abbr)).catch(() => []), hiddenToday().catch(() => [])]); }
  catch (e) { view.innerHTML = failed(e); return; }
  const hid = hidden.filter(g => g.state === "final" && (g.away.abbr === abbr || g.home.abbr === abbr));
  if (hid.length) { view.innerHTML = `<div style="margin-top:12px">${spoilCover(hid, `The ${teamName(abbr)} page`)}</div>`; return; }
  const st = rows.find(r => r.abbr === abbr);
  const fav = favs(), lg = leagueOf(abbr);
  const done = d.schedule.filter(g => g.state === "final").slice(-5).reverse();
  const next = d.schedule.filter(g => g.state !== "final").slice(0, 6);
  const dated = g => `<div class="subhead">${esc(shortDate(g.date))}</div>${gameCard(g, fav)}`;
  const isFav = fav.has(abbr);
  let html = `${backLink("#/league", "League")}<div class="card pad" style="display:flex;align-items:center;gap:14px">
      ${mark(abbr, true)}
      <div style="flex:1"><h1 style="margin:0">${esc(fullName(abbr))}</h1>
      ${st && leagueOf(abbr) === "pwhl" ? `<div class="muted small">${st.w}-${st.otw}-${st.otl}-${st.l} · ${st.pts} pts · ${esc(ordinal(st.league_rank))} in the PWHL${st.season ? ` (${esc(st.season)})` : ""}</div>`
        : st ? `<div class="muted small">${st.w}-${st.l}-${st.otl} · ${st.pts} pts · ${esc(ordinal(st.div_rank))} in the ${esc(st.div)}</div>` : ""}</div>
      <button class="btn small" id="fav">${isFav ? "★ Favorite" : "☆ Favorite"}</button>
    </div>`;
  if (next.length) html += `<h2>Coming up</h2><div class="card">${next.map(dated).join("")}</div>`;
  if (done.length) html += `<h2>Recent results</h2><div class="card">${done.map(dated).join("")}</div>`;
  if (d.milestones?.length) html += `<h2>Close to a milestone</h2><div class="card">${d.milestones.map(m =>
    `<div class="ms-row"><div><b>${plink(m.name, m.id)}</b><div class="muted small">${m.now.toLocaleString()} career ${MS_WORD[m.stat][1]} · next: ${m.target.toLocaleString()}</div></div>
      <span class="pill info">${m.left} to go</span></div>`).join("")}</div>`;
  if (d.wire?.length) html += `<h2>News &amp; moves</h2><div class="card">${d.wire.slice(0, 8).map(i => wireItem(i, new Set(), hidden)).join("")}</div>`;
  const sk = d.stats.skaters.slice(0, 10);
  if (sk.length) {
    html += `<h2>Leaders</h2><div class="card scroll"><table><tr><th>Skater</th><th>GP</th><th>G</th><th>A</th><th>P</th><th>+/-</th></tr>
      ${sk.map(p => `<tr><td>${plink(p.name, p.pid, lg)} <span class="muted small">${esc(p.pos)}</span></td><td>${p.gp}</td><td>${p.g}</td><td>${p.a}</td><td><b>${p.p}</b></td><td>${p.pm > 0 ? "+" : ""}${p.pm}</td></tr>`).join("")}
      </table>${d.stats.goalies.length ? `<table><tr><th>Goalie</th><th>GP</th><th>W-L-OT</th><th>GAA</th><th>SV%</th></tr>
      ${d.stats.goalies.map(p => `<tr><td>${plink(p.name, p.pid, lg)}</td><td>${p.gp}</td><td>${p.w}-${p.l}-${p.otl}</td><td>${p.gaa.toFixed(2)}</td><td>${p.svpct.toFixed(3).replace(/^0/, "")}</td></tr>`).join("")}</table>` : ""}</div>`;
  }
  if (d.roster.length) {
    const groups = { F: "Forwards", D: "Defense", G: "Goalies" };
    html += `<h2>Roster</h2><div class="card scroll"><table><tr><th>#</th><th>Player</th><th>Pos</th><th>Shoots</th><th>Born</th></tr>
      ${Object.entries(groups).map(([k, label]) => `<tr><td colspan="5" class="subhead">${label}</td></tr>` + d.roster.filter(p => p.group === k)
        .sort((x, y) => (x.number || 99) - (y.number || 99))
        .map(p => `<tr><td class="muted">${p.number ?? ""}</td><td><span class="pcell">${photo(lg, abbr, p.id, 28)}${plink(p.name, p.id, lg)}</span></td><td>${esc(p.pos)}</td><td>${esc(p.shoots || "")}</td><td class="muted">${esc((p.born || "").slice(0, 4))} ${esc(p.country || "")}</td></tr>`).join("")).join("")}
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

// ---- players: pages, leaders, search -------------------------------------------------------------
// Photos and logos come from the app's own /img/ (shrunk once on the server, then kept by the phone). Text never
// waits for them: they load lazily into fixed-size spots, and one that's missing just leaves the spot empty.
const photosOn = () => ME?.settings?.photos !== false;
const playerHref = (league, pid) => `#/${league === "pwhl" ? "pplayer" : "player"}/${pid}`;
const plink = (name, pid, league = "nhl") => pid ? `<a class="plink" href="${playerHref(league, pid)}">${esc(name)}</a>` : esc(name);
function photo(league, team, pid, size = 32) {
  if (!photosOn() || !pid || !team) return "";
  return `<img class="ph" src="/img/p/${league}/${encodeURIComponent(team)}/${pid}-${size > 48 ? 192 : 96}.webp" width="${size}" height="${size}" alt="" loading="lazy" decoding="async">`;
}
// One listener for every image on every page: a logo that won't load turns back into the badge; a photo just goes.
document.addEventListener("error", e => {
  const img = e.target;
  if (!(img instanceof HTMLImageElement)) return;
  if (img.closest(".mark.logo")) img.closest(".mark.logo").classList.replace("logo", "nologo");
  else if (img.classList.contains("ph")) img.classList.add("gone");
}, true);

const ageOf = born => {
  if (!born) return null;
  const b = new Date(born), n = new Date();
  return n.getFullYear() - b.getFullYear() - (n < new Date(n.getFullYear(), b.getMonth(), b.getDate()) ? 1 : 0);
};
const pct3 = v => (v || 0).toFixed(3).replace(/^0/, "");
const signed = v => `${v > 0 ? "+" : ""}${v}`;
const POS_NAME = { C: "Center", L: "Left wing", R: "Right wing", D: "Defense", G: "Goalie", F: "Forward" };
let playerTab = "games", allLeagues = false;

function statLine(s, goalie) {
  const cells = goalie
    ? [["GP", s.gp], ["W", s.w], ["L", s.l], ["OT", s.otl], ["GAA", s.gaa.toFixed(2)], ["SV%", pct3(s.svpct)], ["SO", s.so]]
    : [["GP", s.gp], ["G", s.g], ["A", s.a], ["P", s.p], ["+/-", signed(s.pm)], ...(s.toi ? [["TOI", s.toi]] : [])];
  return `<div class="statline">${cells.map(([k, v]) => `<div><b>${esc(v)}</b><span>${k}</span></div>`).join("")}</div>`;
}

// The last games as bars: points for skaters, save % for goalies. Oldest on the left, like reading a season.
function formChart(log, goalie) {
  const games = log.slice(0, 10).reverse();
  if (games.length < 2) return "";
  const W = 300, H = 92, bw = W / games.length;
  const val = g => goalie ? Math.max(0, (g.svpct || 0) - 0.8) / 0.2 : g.p;
  const top = goalie ? 1 : Math.max(3, ...games.map(g => g.p));
  const bars = games.map((g, i) => {
    const v = val(g), h = Math.max(2, (v / top) * (H - 26));
    const label = goalie ? pct3(g.svpct) : g.p;
    return `<rect x="${i * bw + bw * 0.18}" y="${H - 16 - h}" width="${bw * 0.64}" height="${h}" rx="2" class="${goalie ? (g.dec === "W" ? "win" : "") : g.p ? "win" : ""}"/>
      <text x="${i * bw + bw / 2}" y="${H - 20 - h}" text-anchor="middle" class="v">${label}</text>
      <text x="${i * bw + bw / 2}" y="${H - 3}" text-anchor="middle">${esc(TEAMS[g.opp]?.code || g.opp)}</text>`;
  }).join("");
  return `<div class="card pad"><div class="muted small">${goalie ? "Save % — last games" : "Points — last games"}</div>
    <svg class="form" viewBox="0 0 ${W} ${H}" role="img" aria-label="${goalie ? "Save percentage" : "Points"} in the last ${games.length} games">${bars}</svg></div>`;
}

function gameLogTable(log, goalie, league) {
  if (!log.length) return `<div class="card pad muted small">No games yet this season.</div>`;
  const opp = g => `<span class="tm">${g.home ? "vs" : "@"} ${mark(g.opp)}</span>`;
  const link = g => g.game ? ` data-href="${league === "pwhl" ? "#/pgame/" : "#/game/"}${g.game}"` : "";
  return `<div class="card scroll"><table class="log">${goalie
    ? `<tr><th>Date</th><th>Opp</th><th>Dec</th><th>SA</th><th>GA</th><th>SV%</th><th>TOI</th></tr>
      ${log.map(g => `<tr${link(g)}><td class="muted">${esc(shortDate(g.date))}</td><td>${opp(g)}</td><td>${esc(g.dec || "–")}</td><td>${g.sa}</td><td>${g.ga}</td><td>${pct3(g.svpct)}</td><td>${esc(g.toi || "")}</td></tr>`).join("")}`
    : `<tr><th>Date</th><th>Opp</th><th>G</th><th>A</th><th>P</th><th>+/-</th><th>S</th><th>TOI</th></tr>
      ${log.map(g => `<tr${link(g)}><td class="muted">${esc(shortDate(g.date))}</td><td>${opp(g)}</td><td>${g.g}</td><td>${g.a}</td><td><b>${g.p}</b></td><td>${signed(g.pm)}</td><td>${g.shots}</td><td>${esc(g.toi || "")}</td></tr>`).join("")}`}
  </table></div><p class="help">Tap a game to open it.</p>`;
}

function careerBlock(d) {
  const goalie = d.goalie, c = d.career || {};
  const totals = [["Regular season", c.regular], ["Playoffs", c.playoffs]].filter(([, s]) => s && s.gp)
    .map(([label, s]) => `<div class="subhead">${label}</div><div class="pad-x">${statLine(s, goalie)}</div>`).join("");
  const head = goalie ? "<th>GP</th><th>W</th><th>L</th><th>OT</th><th>GAA</th><th>SV%</th>" : "<th>GP</th><th>G</th><th>A</th><th>P</th><th>+/-</th>";
  const cells = s => goalie ? `<td>${s.gp}</td><td>${s.w}</td><td>${s.l}</td><td>${s.otl}</td><td>${s.gaa.toFixed(2)}</td><td>${pct3(s.svpct)}</td>`
    : `<td>${s.gp}</td><td>${s.g}</td><td>${s.a}</td><td><b>${s.p}</b></td><td>${signed(s.pm)}</td>`;
  const pro = d.league === "pwhl" ? "PWHL" : "NHL";
  const others = d.seasons.filter(s => s.league !== pro).length;
  const rows = d.seasons.map(s => `<tr class="${s.league === pro ? "" : "minor"}"><td>${esc(s.season)}</td><td>${esc(s.team || "")}${s.league !== pro ? ` <span class="muted small">${esc(s.league || "")}</span>` : ""}</td>${cells(s)}</tr>`).join("");
  return `${totals ? `<h2>Career</h2><div class="card">${totals}</div>` : ""}
    ${rows ? `<h2>Season by season</h2><div class="card scroll"><table class="seasons${allLeagues ? " all" : ""}"><tr><th>Season</th><th>Team</th>${head}</tr>${rows}</table></div>
      <p class="help">Regular season${allLeagues ? `, every league (grey rows: before or besides the ${pro})` : ` in the ${pro}`}.
      ${others ? `<button class="linkish" data-allleagues>${allLeagues ? `Just the ${pro}` : `Show every league (${others} more)`}</button>` : ""}</p>` : ""}
    ${d.awards?.length ? `<h2>Awards</h2><div class="card">${d.awards.map(a => `<div class="ms-row"><b>${esc(a.name)}</b><span class="muted small">${esc(a.seasons.join(", "))}</span></div>`).join("")}</div>` : ""}`;
}

// MoneyPuck's numbers, each with how it ranks among the league's regulars at that position group.
function advancedBlock(d) {
  const a = d.advanced;
  if (!a) return `<div class="card pad muted small">No advanced stats for this player yet this season.</div>`;
  const bar = (label, value, pct, note) => `<div class="adv"><div class="adv-top"><span>${label}</span><b>${value}</b></div>
    ${pct == null ? "" : `<div class="adv-bar"><span style="width:${Math.max(3, pct)}%"></span></div><div class="muted small">${note ? `${esc(note)} · ` : ""}better than ${pct}% of regulars</div>`}</div>`;
  let rows;
  if (a.goalie) {
    rows = bar("Goals saved above expected", signed(a.gsax), a.pct?.gsax, `${a.ga} allowed on ${a.xga} expected`)
      + (a.hdsv != null ? bar("High-danger save %", pct3(a.hdsv), a.pct?.hdsv, `${a.hd} high-danger shots faced`) : "");
  } else {
    const diff = Math.round((a.goals - a.xg) * 10) / 10;
    const finish = Math.abs(diff) < 0.5 ? "scoring about as expected" : diff > 0 ? `${signed(diff)} more than expected` : `${Math.abs(diff)} fewer than expected`;
    rows = bar("Expected goals", a.xg.toFixed(1), a.pct?.xg, `${a.goals} actual goals: ${finish}`)
      + bar("Expected goals share (5-on-5)", `${a.xgf}%`, a.pct?.xgf, "of the chances while on the ice")
      + bar("Shot attempts share (5-on-5)", `${a.cf}%`, a.pct?.cf, `${a.attempts} own attempts`);
  }
  return `<div class="card pad">${rows}</div>
    <p class="help">Expected goals count each shot by how often shots like it go in (distance, angle, rebound, rush).
      Advanced stats: <a href="${esc(d.credit || "https://moneypuck.com")}" target="_blank" rel="noopener">MoneyPuck.com</a>.</p>`;
}

async function playerView(id, league = "nhl") {
  setNav("league");
  showLoading("Loading player…");
  const path = league === "pwhl" ? `/api/pwhl/player/${id}` : `/api/player/${id}`;
  let d, hidden = [];
  try { [d, hidden] = await Promise.all([fast(path, () => playerView(id, league)), hiddenToday().catch(() => [])]); }
  catch (e) { view.innerHTML = e.status === 404 ? `${backLink("#/league", "League")}<div class="card pad">That player isn't in the league's records.</div>` : failed(e); return; }
  const hid = d.team ? hidden.filter(g => g.state === "final" && (g.away.abbr === d.team || g.home.abbr === d.team)) : [];
  if (hid.length) { view.innerHTML = `<div style="margin-top:12px">${spoilCover(hid, `${d.name}'s page`)}</div>`; return; }
  const f = d.facts || {}, age = ageOf(f.born);
  const chips = [age != null ? `${age} yrs` : "", f.height || "", f.weight ? `${f.weight} lb` : "",
    f.shoots ? `${d.goalie ? "Catches" : "Shoots"} ${f.shoots}` : "", f.country || ""].filter(Boolean);
  const hasAdv = league === "nhl";
  if (playerTab === "advanced" && !hasAdv) playerTab = "games";
  const tabs = [["games", "Games"], ["career", "Career"], ...(hasAdv ? [["advanced", "Advanced"]] : [])];
  const body = { games: () => formChart(d.log, d.goalie) + gameLogTable(d.log, d.goalie, league), career: () => careerBlock(d), advanced: () => advancedBlock(d) };
  view.innerHTML = `${backLink("#/league", "League")}
    <div class="card pad phero">
      ${photosOn() ? `<div class="phero-ph">${photo(league, d.team || "", d.id, 96)}</div>` : ""}
      <div class="phero-main">
        <h1>${esc(d.name)}</h1>
        <div class="muted small">${d.number != null ? `#${d.number} · ` : ""}${esc(POS_NAME[d.pos] || d.pos || "")}</div>
        ${d.team ? `<a class="tm phero-team" href="#/team/${d.team}">${mark(d.team)}<span>${esc(fullName(d.team))}</span></a>` : `<div class="muted small">${d.active ? "" : "Not active"}</div>`}
      </div>
    </div>
    ${chips.length ? `<div class="chipsrow">${chips.map(c => `<span class="chip">${esc(c)}</span>`).join("")}</div>` : ""}
    ${f.birthplace || d.draft ? `<p class="help">${f.birthplace ? `Born in ${esc(f.birthplace)}${f.born ? `, ${esc(new Date(f.born + "T12:00").toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" }))}` : ""}.` : ""}
      ${d.draft ? ` Drafted ${esc(d.draft)}.` : ""}</p>` : ""}
    ${d.season ? `<h2>${esc(d.season.label)} season</h2><div class="card pad">${statLine(d.season, d.goalie)}</div>` : ""}
    <div class="seg" role="tablist">${tabs.map(([k, l]) => `<button data-ptab="${k}" class="${k === playerTab ? "on" : ""}">${l}</button>`).join("")}</div>
    <div id="ptab">${body[playerTab]()}</div>`;
  const bindRows = () => {
    view.querySelectorAll("tr[data-href]").forEach(r => r.addEventListener("click", () => { location.hash = r.dataset.href; }));
    view.querySelector("[data-allleagues]")?.addEventListener("click", () => {
      allLeagues = !allLeagues;
      document.getElementById("ptab").innerHTML = body[playerTab]();
      bindRows();
    });
  };
  bindRows();
  view.querySelectorAll("[data-ptab]").forEach(b => b.addEventListener("click", () => {
    playerTab = b.dataset.ptab;
    view.querySelectorAll("[data-ptab]").forEach(x => x.classList.toggle("on", x === b));
    document.getElementById("ptab").innerHTML = body[playerTab]();
    bindRows();
  }));
}

// League tab: Standings | Leaders, as one row above either page.
const leagueTabs = current => `<div class="seg seg-top">${[["#/league", "standings", "Standings"], ["#/leaders", "leaders", "Leaders"]].map(([href, k, l]) =>
  `<a href="${href}" class="${k === current ? "on" : ""}">${l}</a>`).join("")}</div>`;
const LEADER_CATS = [["points", "Points"], ["goals", "Goals"], ["assists", "Assists"], ["wins", "Wins"], ["savePctg", "SV%"], ["goalsAgainstAverage", "GAA"]];

async function leadersView(quiet = false) {
  setNav("league");
  if (!quiet) showLoading("Loading leaders…");
  const lg = pageLeague();
  let cat = "points";
  try { cat = localStorage.getItem("leadersCat") || cat; } catch { /* fine */ }
  let d, hid = [];
  try { [d, hid] = await Promise.all([fast(`/api/leaders?league=${lg}`, () => leadersView(true)), hiddenToday().catch(() => [])]); }
  catch (e) { view.innerHTML = leagueTabs("leaders") + failed(e); return; }
  hid = hid.filter(g => g.state === "final" && leagueOf(g.home.abbr) === lg);
  if (hid.length) {
    view.innerHTML = leagueTabs("leaders") + leaguePicker(lg) + spoilCover(hid, "The leaders", "include");
    bindLeaguePicker(() => leadersView());
    return;
  }
  const rows = d.cats[cat] || [];
  const fmt = v => cat === "savePctg" ? pct3(v) : cat === "goalsAgainstAverage" ? (+v).toFixed(2) : v;
  const fav = favs();
  view.innerHTML = `${leagueTabs("leaders")}${leaguePicker(lg)}
    <div class="seg">${LEADER_CATS.map(([k, l]) => `<button data-cat="${k}" class="${k === cat ? "on" : ""}">${l}</button>`).join("")}</div>
    <div class="card">${rows.length ? rows.map((r, i) => `<a class="prow${fav.has(r.team) ? " fav" : ""}" href="${playerHref(lg, r.pid)}">
      <span class="rank">${i && fmt(rows[i - 1].value) === fmt(r.value) ? "" : i + 1}</span>${photo(lg, r.team, r.pid, 36)}
      <span class="prow-main"><b>${esc(r.name)}</b><span class="muted small">${mark(r.team)} ${esc(r.pos || "")}</span></span>
      <span class="prow-val">${fmt(r.value)}</span></a>`).join("") : `<div class="pad muted small">No numbers yet this season.</div>`}</div>
    <p class="help">${esc(d.season)} regular season.${["savePctg", "goalsAgainstAverage"].includes(cat) ? " Goalies with enough starts to count." : ""} Your teams' players are highlighted.</p>`;
  bindLeaguePicker(() => leadersView());
  view.querySelectorAll("[data-cat]").forEach(b => b.addEventListener("click", () => {
    try { localStorage.setItem("leadersCat", b.dataset.cat); } catch { /* fine */ }
    leadersView(true);
  }));
}

// Search: players (every roster, both leagues), teams, and the next and last game of the team you typed. The
// player list arrives once (~10 KB); every key press after that is searched on the phone, with no waiting.
let searchText = "";
const fold = s => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

function searchResults(q, players) {
  const f = fold(q.trim());
  if (f.length < 2) return { teams: [], players: [] };
  const score = s => { const t = fold(s); return t.startsWith(f) ? 0 : t.split(/[\s-]/).some(w => w.startsWith(f)) ? 1 : t.includes(f) ? 2 : -1; };
  const teams = Object.entries(TEAMS).map(([abbr, t]) => [abbr, Math.min(...[t.name, t.place, `${t.place} ${t.name}`, t.code || abbr].map(score).map(x => x < 0 ? 9 : x))])
    .filter(([, s]) => s < 9).sort((x, y) => x[1] - y[1] || teamName(x[0]).localeCompare(teamName(y[0]))).map(([a]) => a);
  const fav = favs();
  const found = players.map(p => [p, score(p[1])]).filter(([, s]) => s >= 0)
    .sort((x, y) => x[1] - y[1] || (fav.has(y[0][2]) - fav.has(x[0][2])) || x[0][1].localeCompare(y[0][1])).slice(0, 30).map(([p]) => p);
  return { teams: teams.slice(0, 6), players: found };
}

async function searchView() {
  setNav("search");
  view.innerHTML = `<h1>Search</h1>
    <input class="field search-box" id="q" type="search" placeholder="Players and teams" autocomplete="off" autocapitalize="off" spellcheck="false" value="${esc(searchText)}">
    <div id="results"></div>`;
  const box = document.getElementById("q"), out = document.getElementById("results");
  if (!searchText) box.focus();
  let players = null;
  const draw = async () => {
    searchText = box.value;
    if (!players) { out.innerHTML = searchText.trim().length >= 2 ? `<div class="empty">Loading players…</div>` : ""; return; }
    const r = searchResults(searchText, players);
    if (searchText.trim().length < 2) { out.innerHTML = `<p class="help">Type a name: Pastrnak, Keller, Bruins, Fleet…</p>`; return; }
    if (!r.teams.length && !r.players.length) { out.innerHTML = `<div class="card pad muted small">Nothing matches “${esc(searchText.trim())}”.</div>`; return; }
    out.innerHTML = `${r.teams.length ? `<h2>Teams</h2><div class="card">${r.teams.map(a => `<a class="prow" href="#/team/${a}">${mark(a, true)}<span class="prow-main"><b>${esc(fullName(a))}</b><span class="muted small">${leagueOf(a) === "pwhl" ? "PWHL" : esc(TEAMS[a]?.div || "NHL")}</span></span></a>`).join("")}</div>
      <div id="teamgames"></div>` : ""}
      ${r.players.length ? `<h2>Players</h2><div class="card">${r.players.map(([pid, name, team, pos]) => `<a class="prow" href="${playerHref(leagueOf(team), pid)}">${photo(leagueOf(team), team, pid, 36)}
        <span class="prow-main"><b>${esc(name)}</b><span class="muted small">${mark(team)} ${esc(teamName(team))} · ${esc(pos || "")}</span></span></a>`).join("")}</div>` : ""}`;
    if (r.teams.length) {
      const abbr = r.teams[0], want = searchText;
      const t = await fast(`/api/team/${encodeURIComponent(abbr)}`, () => {}).catch(() => null);
      const box2 = document.getElementById("teamgames");
      if (!t || !box2 || want !== searchText) return;
      const last = t.schedule.filter(g => g.state === "final").slice(-1), next = t.schedule.filter(g => g.state !== "final").slice(0, 1);
      const hidden = await hiddenToday().catch(() => []);
      const shown = [...next, ...last].filter(g => !hidden.some(h => h.id === g.id));
      if (shown.length) box2.innerHTML = `<h2>${esc(teamName(abbr))} games</h2><div class="card">${shown.map(g => `<div class="subhead">${esc(shortDate(g.date))}</div>${gameCard(g, favs())}`).join("")}</div>`;
    }
  };
  box.addEventListener("input", draw);
  draw();
  try { players = (await fast("/api/search", () => {})).players; } catch (e) { out.innerHTML = failed(e); return; }
  draw();
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
    <a class="card pad whatsnew-link" href="#/new"><b>What's new</b>${unseenChanges().length ? ` <span class="pill info">${unseenChanges().length} new</span>` : ""}<span class="muted small">Every update to the app →</span></a>
    <p class="help">Changes save as you make them.</p>

    <div class="group-title">You</div>
    <div class="section-head"><h2>Your teams</h2>${fav.length ? `<button class="btn small" id="editteams">${open ? "Done" : "Edit"}</button>` : ""}</div>
    <div class="card">${open ? (fav.length ? "" : `<div class="pad small">Tap your teams. They're pinned to the top of Tonight, highlighted everywhere, and the ones you get alerts for.</div>`) + picker : mine}</div>
    ${open && fav.length ? `<p class="help">Tap a team again to remove it.</p>` : ""}

    <h2>Your name</h2>
    <div class="card"><label class="row-field"><span><b>Name friends see</b><span class="muted small">On Pick'em and on games you're watching. Empty = "${esc(ME.email.split("@")[0])}". Your email is never shown.</span></span>
      <input class="field" id="nickname" maxlength="24" autocomplete="nickname" placeholder="${esc(ME.email.split("@")[0])}" value="${esc(s.nickname || "")}"></label></div>

    <h2>Where you watch</h2>
    <div class="card">
      <label class="row-field"><span><b>Home market</b><span class="muted small">Whose games are blacked out on ESPN+ for you and shown on local TV instead</span></span>
        <select id="local" class="field"><option value="">None</option>${nhlGroups.map(([g, list]) => `<optgroup label="${esc(g)}">${list.map(a =>
          `<option value="${a}" ${a === local ? "selected" : ""}>${esc(fullName(a))}</option>`).join("")}</optgroup>`).join("")}</select></label>
      ${guess ? `<div class="pad small suggest">Live near ${esc(TEAMS[guess].place)}? <button class="btn small" id="useguess">Use the ${esc(teamName(guess))}</button></div>` : ""}
      <div class="subhead">What you can watch with</div>
      <div class="checks">${Object.entries(ME.services).map(([k, v]) =>
        `<label><input type="checkbox" name="services" value="${k}" ${services.includes(k) ? "checked" : ""}>${esc(v.label)}</label>`).join("")}</div>
    </div>
    <p class="help">Each game then says whether you have it. In Massachusetts the home market is the Bruins.</p>

    <div class="group-title">Alerts &amp; spoilers</div>
    <h2>Alerts</h2>
    <div class="card" id="notif"><div class="empty">Checking this device…</div></div>
    <div class="card checks" style="margin-top:10px">${[["start", "Puck drop"], ["goals", "Every goal (with career milestones)"], ["final", "Final scores"], ["trades", "Trades"], ["fights", "Fights"]].map(([k, l]) =>
      `<label><input type="checkbox" name="notify" value="${k}" ${s.notify?.[k] ? "checked" : ""}>${l}</label>`).join("")}</div>
    <p class="help">For your teams only. <a href="#/app">Getting the app and alerts on your phone</a>.</p>

    <h2>Spoiler-free</h2>
    ${fav.length ? `<div class="card checks">${fav.map(a =>
      `<label><input type="checkbox" name="spoilteams" value="${a}" ${spoilers().teams.includes(a) ? "checked" : ""}>Always hide ${esc(teamName(a))} scores</label>`).join("")}</div>` : ""}
    <p class="help">A hidden game stays out of sight everywhere (scores, goal and final alerts, standings, the Wire) until you tap
      "I've seen it". ${fav.length ? "Tick a team to hide all their games, or open" : "Open"} any game and tap "🙈 Watching later" to hide just that one. It switches off by itself the day after.</p>

    <div class="group-title">More</div>
    <h2>Display</h2>
    <div class="card checks"><label><input type="checkbox" id="animations" ${s.animations !== false ? "checked" : ""}>Animations between pages</label></div>
    <p class="help">Quick slides between tabs and pages. Turn them off for instant switching. They're also off whenever your phone's Reduce Motion setting is on.</p>
    <div class="seg" role="group" aria-label="Team marks">${[["badges", "Team badges"], ["logos", "Team logos"]].map(([k, l]) =>
      `<button data-marks="${k}" class="${(s.marks || "badges") === k ? "on" : ""}">${l}</button>`).join("")}</div>
    <p class="help">How teams show up everywhere: coloured badges with their letters, or the teams' own logos.</p>
    <div class="card checks"><label><input type="checkbox" id="photos" ${s.photos !== false ? "checked" : ""}>Player photos</label></div>
    <p class="help">Faces on player pages, leaders, rosters and the three stars. They're small and the app keeps them after the first look; turn them off for the leanest pages.</p>
    <div class="card checks"><label><input type="checkbox" id="odds" ${s.odds !== false ? "checked" : ""}>Show odds</label></div>
    <p class="help">Who's favoured to win and how many goals are expected, from DraftKings' lines. Just for fun: nothing here links to betting.</p>
    <div class="seg" role="group" aria-label="Buttons on touch screens">${[["right", "Right-handed"], ["left", "Left-handed"]].map(([k, l]) =>
      `<button data-hand="${k}" class="${(s.hand || "right") === k ? "on" : ""}">${l}</button>`).join("")}</div>
    <p class="help">On phones, foldables and tablets, game page buttons sit on this side, under your thumb. On a computer they're centred.</p>

    <h2>Calendar</h2>
    <div class="card" id="cal"><div class="empty">Loading…</div></div>
    <p class="help">Every game for your teams, with where to watch. Your phone checks it every few hours. The link is personal; don't share it.</p>

    <h2>Help</h2>
    <a class="card pad whatsnew-link" href="#/report"><b>Report a problem or suggest an idea</b><span class="muted small">Goes straight to the to-do list →</span></a>
    <div id="myreports"></div>
    ${ME.admin ? `<a class="card pad whatsnew-link" href="#/admin" style="margin-top:10px"><b>Admin</b><span class="muted small">People, invites, insiders, sources →</span></a>` : ""}
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
  document.getElementById("animations").addEventListener("change", e => saveSettings({ animations: e.target.checked }));
  document.getElementById("odds").addEventListener("change", e => saveSettings({ odds: e.target.checked }));
  document.getElementById("photos").addEventListener("change", e => saveSettings({ photos: e.target.checked }));
  view.querySelectorAll("button[data-marks]").forEach(b => b.addEventListener("click", () => {
    saveSettings({ marks: b.dataset.marks });
    settingsView();   // every mark on the page changes
  }));
  document.querySelectorAll("button[data-hand]").forEach(b => b.addEventListener("click", () => {
    document.querySelectorAll("button[data-hand]").forEach(x => x.classList.toggle("on", x === b));
    applyHand(b.dataset.hand); saveSettings({ hand: b.dataset.hand });
  }));
  document.getElementById("nickname").addEventListener("change", e => saveSettings({ nickname: e.target.value.trim().slice(0, 24) }));
  view.querySelectorAll("input[name=spoilteams]").forEach(i => i.addEventListener("change", () => {
    saveSettings({ spoilers: { ...spoilers(), teams: picked("spoilteams") } });
    hiddenCache = { at: 0, list: [] };
  }));
  view.querySelectorAll("input[name=notify]").forEach(i => i.addEventListener("change", () => {
    const on = new Set(picked("notify"));
    saveSettings({ notify: Object.fromEntries(["start", "goals", "final", "trades", "fights"].map(k => [k, on.has(k)])) });
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
  view.innerHTML = `${backLink(reportFrom || "#/")}
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

// Page views (anonymous, your own not counted): which pages friends actually open.
function usageBlock(u) {
  if (!u?.pages.length) return `<h2>Page views</h2><div class="card"><div class="empty">No views counted yet.</div></div>`;
  const month = u.pages.reduce((n, p) => n + p.month, 0);
  return `<h2>Page views</h2>
    <div class="card scroll"><table><tr><th>Page</th><th>7 days</th><th>30 days</th><th>Since ${esc(u.first)}</th></tr>
      ${u.pages.map(p => `<tr><td>${esc(VIEW_NAME[p.route] || p.route)}</td><td>${p.week}</td><td>${p.month}</td><td>${p.all}</td></tr>`).join("")}
    </table></div>
    <p class="help">${month} views in the last 30 days. Counted per page and day, never who; your own views aren't counted.</p>`;
}

async function adminView() {
  setNav("settings");
  if (!ME.admin) { view.innerHTML = `<div class="empty">Admin only.</div>`; return; }
  let d;
  try { d = await api("/api/admin"); } catch (e) { view.innerHTML = failed(e); return; }
  const people = st => d.users.filter(u => u.status === st);
  const row = (u, buttons) => `<div class="person"><span class="em">${esc(u.email)}</span><span class="when">${esc(ago(u.requested || u.decided))}</span>${buttons}</div>`;
  const btn = (email, status, label, primary) => `<button class="btn small${primary ? " primary" : ""}" data-email="${esc(email)}" data-status="${status}">${label}</button>`;
  const pending = people("pending"), approved = people("approved"), other = d.users.filter(u => ["denied", "revoked"].includes(u.status));
  const openInvites = d.invites.filter(i => i.uses.length < i.max_uses);
  view.innerHTML = `${backLink("#/settings", "Settings")}
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
    ${usageBlock(d.usage)}
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
// ---- page transitions ------------------------------------------------------------------------
// "Slapshot": the old page goes at once, and the new one flies in from the side already at speed, overshoots its
// spot and snaps back like a puck hitting the twine. Tabs come
// from their side of the tab bar, game and team pages from the right, going back from the left. It plays only once
// the new page's content is on screen, never for live refreshes or the same page re-shown; off with Settings >
// Display or the phone's Reduce Motion.
const NAV_ORDER = { "": 0, day: 0, picks: 1, wire: 2, league: 3, standings: 3, teams: 3, settings: 4, new: 5, app: 5, report: 5, admin: 5 };
const DETAIL = new Set(["game", "pgame", "team"]);
let lastHash = null, lastPage = null, pendingShot = 0, cameFromApp = false;   // pendingShot: +1 from the right, -1 from the left
const applyHand = hand => { document.documentElement.dataset.hand = hand === "left" ? "left" : "right"; };
const motionOn = () => ME?.settings?.animations !== false && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// "← Back" on sub-pages: the page you came from when you got here inside the app, otherwise a sensible parent.
const backLink = (fallback, label = "Back") => `<a class="back" href="${fallback}" data-back>${BACK_ICON}<span>${esc(label)}</span></a>`;
const BACK_ICON = `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

function shotFrom(prev, next) {
  if (DETAIL.has(next)) return 1;
  if (DETAIL.has(prev)) return -1;
  return (NAV_ORDER[next] ?? 0) >= (NAV_ORDER[prev] ?? 0) ? 1 : -1;
}

// Page views for /admin: counted per page pattern on the phone, sent in batches (sendBeacon: never in a page's way).
// Anonymous on the server; the owner's own views aren't counted.
const VIEWS = {};
// Same checks as renderRoute: a page whose argument it rejects is counted as what it shows instead.
const VIEW_PAGE = { standings: "league", teams: "league" };
const VIEW_ARG = { day: ["date", /^\d{4}-\d{2}-\d{2}$/], picks: ["date", /^\d{4}-\d{2}-\d{2}$/], game: ["id", /^\d+$/],
  pgame: ["id", /^\d+$/], team: ["team", /^(PW-)?[A-Z]{2,3}$/], player: ["id", /^\d+$/], pplayer: ["id", /^\d+$/] };
const VIEW_PLAIN = new Set(["picks", "wire", "league", "settings", "app", "new", "report", "leaders", "search"]);   // fine without an argument
const VIEW_NAME = { tonight: "Tonight", "day/:date": "Another day", "game/:id": "NHL game", "pgame/:id": "PWHL game",
  picks: "Pick'em", "picks/:date": "Pick'em, another day", wire: "Wire", league: "League", "team/:team": "Team page",
  settings: "Settings", app: "Get the app", new: "What's new", report: "Report a problem",
  "player/:id": "NHL player", "pplayer/:id": "PWHL player", leaders: "Leaders", search: "Search" };

function countView() {
  if (ME?.status !== "approved" || ME.admin) return;
  const [, raw = "", arg = ""] = (location.hash || "#/").split("/");
  const page = VIEW_PAGE[raw] || raw, [kind, ok] = VIEW_ARG[page] || [];
  const key = ok?.test(arg) ? `${page}/:${kind}` : VIEW_PLAIN.has(page) ? page : "tonight";
  VIEWS[key] = (VIEWS[key] || 0) + 1;
}

// Leaving the app: sendBeacon (survives the page going away). Otherwise a fetch, and a batch that doesn't land
// (offline, an expired sign-in redirecting to the login page) goes back in the count for next time.
function sendViews(leaving = false) {
  if (!Object.keys(VIEWS).length) return;
  const batch = { ...VIEWS }, body = JSON.stringify({ views: batch });
  for (const k in VIEWS) delete VIEWS[k];
  const putBack = () => { for (const k in batch) VIEWS[k] = (VIEWS[k] || 0) + batch[k]; };
  if (leaving && navigator.sendBeacon?.("/api/views", new Blob([body], { type: "application/json" }))) return;
  fetch("/api/views", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true, redirect: "error" })
    .then(res => { if (!res.ok) putBack(); }, putBack);
}

function route() {
  if (location.hash !== lastHash) countView();   // a navigation, not a re-render (league switch, spoiler peek)
  const page = (location.hash || "#/").split("/")[1] || "";
  const changed = lastHash !== null && location.hash !== lastHash;
  pendingShot = changed && motionOn() && ME?.status === "approved" ? shotFrom(lastPage, page) : 0;
  if (changed) cameFromApp = true; else if (lastHash === null) cameFromApp = false;
  lastHash = location.hash; lastPage = page;
  return renderRoute();
}

function slapshot(d) {
  view.animate([
    // Whole-pixel sideways moves only: no scaling or skew, so the text drawn while moving is the same as the text at
    // rest and nothing shifts when it stops.
    { transform: `translate3d(${56 * d}px, 0, 0)`, opacity: 0, offset: 0 },   // already flying
    { transform: `translate3d(${-7 * d}px, 0, 0)`, opacity: 1, offset: 0.55 }, // hits, overshoots
    { transform: `translate3d(${2 * d}px, 0, 0)`, offset: 0.8 },               // snaps back
    { transform: "translate3d(0, 0, 0)", opacity: 1, offset: 1 },
  ], { duration: 280, easing: "cubic-bezier(.12, .8, .3, 1)" });
}

// Fire when a navigation's real content lands in the page (not the "Loading…" placeholder).
new MutationObserver(() => {
  if (!pendingShot) return;
  const first = view.firstElementChild;
  if (!first || (first.classList.contains("empty") && /^Loading/.test(first.textContent))) return;
  const d = pendingShot;
  pendingShot = 0;
  slapshot(d);
}).observe(view, { childList: true });

function renderRoute() {
  clearTimeout(refreshTimer);
  setCompact(false);
  if (ME.status !== "approved") return gateView();
  document.getElementById("tabs").hidden = false;
  const [, page, arg] = (location.hash || "#/").split("/");
  if (page !== "settings") editingTeams = false;
  if (page !== "report") reportFrom = location.hash || "#/";
  document.getElementById("foot").hidden = page === "report";
  window.scrollTo(0, 0);
  if (page === "day" && /^\d{4}-\d{2}-\d{2}$/.test(arg || "")) return tonightView(arg);
  if (page === "game" && /^\d+$/.test(arg || "")) return gameView(arg);
  if (page === "pgame" && /^\d+$/.test(arg || "")) return gameView(arg, false, "pwhl");
  if (page === "picks") return pickemView(/^\d{4}-\d{2}-\d{2}$/.test(arg || "") ? arg : undefined);
  if (page === "wire") return wireView();
  if (page === "standings" || page === "league" || page === "teams") {  // Standings and Teams became one League tab
    let mode = "division";
    try { mode = localStorage.getItem("standingsMode") || mode; } catch { /* fine */ }
    return standingsView(mode);
  }
  if (page === "team" && /^(PW-)?[A-Z]{2,3}$/.test(arg || "")) return teamView(arg);
  if (page === "player" && /^\d+$/.test(arg || "")) return playerView(arg);
  if (page === "pplayer" && /^\d+$/.test(arg || "")) return playerView(arg, "pwhl");
  if (page === "leaders") return leadersView();
  if (page === "search") return searchView();
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
    applyHand(ME.settings?.hand);
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
  // Spoiler-free buttons can sit on any page (cards, game page, covers); one listener handles them all.
  view.addEventListener("click", e => {
    if (e.target.closest("[data-back]") && cameFromApp) { e.preventDefault(); history.back(); return; }
    const b = e.target.closest("[data-spoil]");
    if (b) { e.preventDefault(); spoilerAction(b.dataset.spoil, b.dataset.k); return; }
    const u = e.target.closest("[data-unspoil]");
    if (u) { u.closest(".witem").classList.remove("spoil"); u.remove(); }
  });
  // Phones keep the app's last page in memory for days: coming back after a while shows today, not last night.
  let hiddenAt = 0;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { hiddenAt = Date.now(); sendViews(true); return; }
    if (hiddenAt && Date.now() - hiddenAt > 5 * 60000) { countView(); route(); }   // coming back = a fresh open
  });
  route();
  setTimeout(prefetch, 2500);  // the other tabs, quietly, once the first page is up
  setInterval(sendViews, 60000);
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
}

start();
