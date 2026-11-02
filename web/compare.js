// Compare: two players or two teams side by side. A side in the address is a team key (BOS, PW-BOS, CM-57), p<id> for an NHL
// player or q<id> for a PWHL one. One side given: pick the other. Loaded on demand (web/app.js compareView); it asks the
// server for nothing new, only the pages it would show anyway.
const CSS = `
.cp-head { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 8px; padding: 16px 12px; border-radius: 14px; color: #fff;
  background: linear-gradient(101deg, color-mix(in srgb, var(--a) 68%, #0a0d12) 50%, color-mix(in srgb, var(--h) 68%, #0a0d12) 50%); }
.cp-side { display: grid; justify-items: center; gap: 6px; min-width: 0; text-align: center; color: inherit; text-decoration: none; }
.cp-side .mark.big { width: 64px; height: 44px; }
.cp-side .ph { width: 64px; height: 64px; border-radius: 50%; background: rgba(255, 255, 255, .1); }
.cp-name { font: 800 22px/1.02 Arena, Score, system-ui, sans-serif; text-transform: uppercase; letter-spacing: .012em; overflow-wrap: anywhere; }
.cp-sub { font-size: 12px; color: rgba(255, 255, 255, .78); }
.cp-vs { font: 800 20px/1 Arena, Score, system-ui, sans-serif; opacity: .6; }
.cp-rows { margin-top: 12px; }
.cp-swap { display: block; margin: 2px auto 0; font-size: 12px; color: rgba(255, 255, 255, .78); }
.cp-pick { margin-top: 10px; }
.cmp .v.best { font-weight: 800; }
.cmp .v:not(.best) { font-weight: 500; }`;

const isPlayer = s => /^[pq]\d{1,8}$/.test(s || "");
const pct = v => (v || 0).toFixed(3).replace(/^0/, "");
const per = (n, gp) => gp ? (n / gp).toFixed(2) : "0.00";
const plus = v => `${v > 0 ? "+" : ""}${v}`;

// [label, value for one side, how to show it, lower is better]
const SKATER = [["Games", s => s.gp], ["Goals", s => s.g], ["Assists", s => s.a], ["Points", s => s.p],
  ["Points a game", s => +per(s.p, s.gp), v => v.toFixed(2)], ["Goals a game", s => +per(s.g, s.gp), v => v.toFixed(2)],
  ["Plus/minus", s => s.pm, plus], ["Shots", s => s.shots], ["Power-play goals", s => s.ppg]];
const GOALIE = [["Games", s => s.gp], ["Wins", s => s.w], ["Save %", s => s.svpct, pct], ["Goals against avg", s => s.gaa, v => v.toFixed(2), true], ["Shutouts", s => s.so]];
const TEAM = [["Points", r => r.pts], ["Wins", r => r.w], ["Points %", r => r.pct, pct], ["Goals for", r => r.gf], ["Goals against", r => r.ga, null, true],
  ["Goal difference", r => r.gd, plus], ["Regulation wins", r => r.rw], ["Last 10", r => r.l10 && +r.l10.split("-")[0], v => `${v} wins`]];

function rows(spec, a, b, ac, bc, esc) {
  return spec.map(([label, get, show, low]) => {
    const x = a ? get(a) : null, y = b ? get(b) : null;
    if (x == null || y == null || Number.isNaN(x) || Number.isNaN(y) || (!x && !y)) return "";   // nothing either side (college has no points)
    const f = v => esc(show ? show(v) : v), lift = Math.max(0, -Math.min(x, y));   // a negative value can't be a bar length
    const nx = x + lift, ny = y + lift, total = nx + ny || 1, xBest = low ? x < y : x > y, yBest = low ? y < x : y > x;
    return `<div class="cmp"><span class="v${xBest ? " best" : ""}">${f(x)}</span>
      <div><div class="lbl">${esc(label)}</div><div class="bar"><i style="width:${nx / total * 100}%;background:${ac}"></i><i style="width:${ny / total * 100}%;background:${bc}"></i></div></div>
      <span class="v${yBest ? " best" : ""}">${f(y)}</span></div>`;
  }).join("");
}

// One side's data, and its header. Throws what the page's own request would.
async function load(ctx, side) {
  const T = ctx.teams();
  if (isPlayer(side)) {
    const league = side[0] === "q" ? "pwhl" : "nhl", id = side.slice(1);
    const d = await ctx.fast(league === "pwhl" ? `/api/pwhl/player/${id}` : `/api/player/${id}`, () => {});
    return { kind: d.goalie ? "goalie" : "skater", name: d.name, team: d.team, colour: T[d.team]?.color || "#444", href: ctx.playerHref(league, d.id), d,
      art: ctx.photo(league, d.team || "", d.id, 96), sub: `${d.pos || ""}${d.team ? ` · ${T[d.team]?.code || d.team}` : ""}` };
  }
  if (!ctx.TEAM_KEY.test(side || "") || !T[side]) throw Object.assign(new Error("no team"), { detail: "That team isn't in the app." });
  const [d, list] = await Promise.all([ctx.fast(`/api/team/${encodeURIComponent(side)}`, () => {}), ctx.standings(ctx.leagueOf(side)).catch(() => [])]);
  const row = list.find(r => r.abbr === side);
  return { kind: "team", name: ctx.teamName(side), team: side, colour: T[side].color || "#444", href: `#/team/${encodeURIComponent(side)}`, d, row,
    art: ctx.mark(side, true), sub: row ? `${row.w}-${row.l}${row.otl != null ? `-${row.otl}` : ""}` : "" };
}

// The picker: same search as the Search page, limited to what can be compared with `one`.
async function picker(ctx, one, oneSide) {
  const box = ctx.view.querySelector("#cp-q"), out = ctx.view.querySelector("#cp-out");
  let players = [];
  try { if (one.kind !== "team") players = (await ctx.fast("/api/search", () => {})).players; } catch { /* the box still works for teams */ }
  const draw = () => {
    const q = box.value;
    if (q.trim().length < 2) { out.innerHTML = ""; return; }
    const r = ctx.searchResults(q, players);
    const link = (side, html) => `<a class="prow" href="#/compare/${encodeURIComponent(oneSide)}/${encodeURIComponent(side)}">${html}</a>`;
    const items = one.kind === "team"
      ? r.teams.filter(a => a !== oneSide).map(a => link(a, `${ctx.mark(a, true)}<span class="prow-main"><b>${ctx.esc(ctx.fullName(a))}</b></span>`))
      : r.players.filter(p => ctx.playerSide(p) !== oneSide && (p[3] === "G") === (one.kind === "goalie")).slice(0, 12)
        .map(p => link(ctx.playerSide(p), `${ctx.photo(ctx.leagueOf(p[2]), p[2], p[0], 36)}<span class="prow-main"><b>${ctx.esc(p[1])}</b><span class="muted small">${ctx.mark(p[2])} ${ctx.esc(ctx.teamName(p[2]))}</span></span>`));
    out.innerHTML = items.length ? `<div class="card">${items.join("")}</div>` : `<div class="card pad muted small">Nothing to compare matches “${ctx.esc(q.trim())}”.</div>`;
  };
  box.addEventListener("input", draw);
}

// Games between the two this season, from the team page's ribbon.
function series(ctx, x, y) {
  const games = (x.d.ribbon || []).filter(g => g.r && g.o === y.team);
  if (!games.length) return "";
  const won = games.filter(g => g.r === "W").length, lost = games.filter(g => g.r !== "W" && g.r !== "T").length;
  const lead = won === lost ? `Even at ${won}-${lost}` : `${ctx.esc(won > lost ? x.name : y.name)} lead ${Math.max(won, lost)}-${Math.min(won, lost)}`;
  return `<h2>This season: ${lead}</h2><div class="card">${games.map(g => `<a class="grow" href="${ctx.gameHref({ id: g.id, league: ctx.leagueOf(x.team) })}"><span class="grow-date">${ctx.esc(ctx.shortDate(g.d))}</span>
    <span class="tm grow-opp">${g.h ? "vs" : "@"} ${ctx.mark(y.team)} <span>${ctx.esc(y.name)}</span></span><span class="grow-r"><b class="${g.r === "W" ? "res-w" : g.r === "T" ? "" : "res-l"}">${g.r === "OT" ? "OTL" : g.r}</b> ${g.u}–${g.t}</span></a>`).join("")}</div>`;
}

export async function show(ctx, aSide, bSide) {
  if (!document.getElementById("cp-css")) document.head.append(Object.assign(document.createElement("style"), { id: "cp-css", textContent: CSS }));
  const { view, esc } = ctx, back = ctx.backLink("#/league", "Back"), page = ctx.page();
  if (!aSide) { view.innerHTML = `${back}<div class="card pad">Open a team or a player and tap Compare, or search for “Bruins vs Leafs”.</div>`; return; }
  const [a, b, hidden] = await Promise.all([load(ctx, aSide), bSide ? load(ctx, bSide) : null, ctx.hiddenToday().catch(() => [])]);
  if (ctx.page() !== page) return;
  // Numbers that a hidden result would change stay covered, as on team and player pages.
  const hid = hidden.filter(g => g.state === "final" && [a, b].some(s => s?.team && (g.away.abbr === s.team || g.home.abbr === s.team)));
  if (hid.length) { view.innerHTML = `<div style="margin-top:12px">${ctx.spoilCover(hid, "This comparison")}</div>`; return; }
  const side = (s, swap) => `<div class="cp-side"><a class="cp-side" href="${s.href}">${s.art}<span class="cp-name">${esc(s.name)}</span><span class="cp-sub">${esc(s.sub)}</span></a>${swap ? `<a class="cp-swap" href="#/compare/${encodeURIComponent(swap)}">Change</a>` : ""}</div>`;
  const ac = ctx.apart(a.colour, b?.colour || a.colour), bc = b?.colour || a.colour;
  const head = `<div class="cp-head" style="--a:${esc(b ? ac : a.colour)};--h:${esc(b ? bc : "#20242c")}">${side(a, bSide)}<span class="cp-vs">VS</span>${b ? side(b, aSide) : `<div class="cp-side"><span class="cp-name">Who?</span></div>`}</div>`;
  if (!b) {
    const what = a.kind === "team" ? "Another team" : a.kind === "goalie" ? "Another goalie" : "Another skater";
    view.innerHTML = `${back}${head}<div class="cp-pick"><input class="field search-box" id="cp-q" type="search" placeholder="${what}" autocomplete="off" autocapitalize="off" spellcheck="false"></div><div id="cp-out"></div>`;
    await picker(ctx, a, aSide);
    view.querySelector("#cp-q")?.focus({ preventScroll: true });
    return;
  }
  if ((a.kind === "team") !== (b.kind === "team") || (a.kind !== "team" && a.kind !== b.kind)) {
    view.innerHTML = `${back}${head}<div class="card pad cp-rows muted small">A ${a.kind} and a ${b.kind} don't share numbers worth comparing.</div>`;
    return;
  }
  const section = (title, body) => body ? `<h2>${esc(title)}</h2><div class="card compare">${body}</div>` : "";
  let body;
  if (a.kind === "team") {
    body = section("Season", rows(TEAM, a.row, b.row, ac, bc, esc)) + series(ctx, a, b);
  } else {
    const spec = a.kind === "goalie" ? GOALIE : SKATER, label = a.d.season?.label || b.d.season?.label || "This season";
    body = section(`${label} season`, rows(spec, a.d.season, b.d.season, ac, bc, esc))
      + section("Career, regular season", rows(spec, a.d.career?.regular, b.d.career?.regular, ac, bc, esc));
  }
  view.innerHTML = `${back}${head}<div class="cp-rows">${body || `<div class="card pad muted small">No numbers to compare yet.</div>`}</div>`;
}
