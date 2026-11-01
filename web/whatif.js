// What if?: tap who wins the games still to play and the standings re-sort under your thumb. Everything happens on the
// phone from the table already on the page; nothing is saved. Loaded on demand from League (web/app.js).
const CSS = `
.wi { margin: 10px 0 2px; padding: 12px 14px; }
.wi-h { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; font-weight: 700; }
.wi-h .linkish { margin-left: auto; }
.wi-g { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 8px; padding: 4px 0; }
.wi-t { display: flex; align-items: center; gap: 8px; min-height: 40px; min-width: 0; padding: 4px 8px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg); color: var(--text); font: inherit; font-size: 13px; font-weight: 650; cursor: pointer; }
.wi-t.h { flex-direction: row-reverse; }
.wi-t.on { background: var(--c); color: #fff; border-color: transparent; }
.wi-t.on.light { color: #111; }
.wi-at { font-size: 12px; color: var(--muted); }
.wi-t em { font: 800 15px/1 Score, system-ui, sans-serif; font-style: normal; margin-inline-start: auto; }
.wi-t.h em { margin-inline-start: 0; margin-inline-end: auto; }
.wi-moves { margin-top: 8px; font-size: 13px; }
.wi-moves div { padding: 2px 0; }
.wi-more { color: var(--accent); font-size: 11px; margin-left: 3px; }`;

const beats = (x, y) => y.pts - x.pts || x.gp - y.gp || y.rw - x.rw || y.w - x.w || y.gd - x.gd;
const ordinal = n => `${n}${["th", "st", "nd", "rd"][n % 100 > 10 && n % 100 < 14 ? 0 : n % 10] || "th"}`;

// The table after these results: `picks` = Map(game id as text -> { winner, ot }). Ties go points, fewer games, regulation wins,
// wins, goal difference: the NHL's order, near enough for a toy.
export function project(rows, games, picks) {
  if (!picks.size) return rows;
  const out = new Map(rows.map(r => [r.abbr, { ...r, more: 0 }]));
  for (const g of games) {
    const p = picks.get(String(g.id));
    if (!p) continue;
    const win = out.get(p.winner), lose = out.get(p.winner === g.home.abbr ? g.away.abbr : g.home.abbr);
    if (!win || !lose) continue;
    win.gp++; win.w++; win.pts += 2; win.more += 2; win.gd++; if (!p.ot) win.rw++;
    lose.gp++; lose.gd--;
    if (p.ot) { lose.otl++; lose.pts++; lose.more++; } else lose.l++;
  }
  const list = [...out.values()].sort(beats);
  list.forEach((r, i) => { r.league_rank = i + 1; });
  const group = (key, set) => { const seen = {}; for (const r of list) set(r, seen[r[key]] = (seen[r[key]] || 0) + 1); };
  group("div", (r, n) => { r.div_rank = n; });
  group("conf", (r, n) => { r.conf_rank = n; });
  const wild = list.filter(r => r.div_rank > 3), seen = {};
  list.forEach(r => { r.wildcard = 0; });
  for (const r of wild) r.wildcard = seen[r.conf] = (seen[r.conf] || 0) + 1;
  return list;
}

const place = r => r.div_rank <= 3 ? `${ordinal(r.div_rank)} in the ${r.div}` : r.wildcard <= 2 ? `wild card ${r.wildcard}` : `${r.wildcard - 2} out of a wild card`;

// Rows glide from where they were to where they are now, even between tables. Only transforms, whole pixels.
function glide(table, motion, redraw) {
  const spots = new Map([...table.querySelectorAll("tr[data-t]")].map(tr => [tr.dataset.t, tr.getBoundingClientRect().top]));
  redraw();
  if (!motion) return;
  for (const tr of table.querySelectorAll("tr[data-t]")) {
    const from = spots.get(tr.dataset.t), dy = from == null ? 0 : Math.round(from - tr.getBoundingClientRect().top);
    if (dy) tr.animate([{ transform: `translateY(${dy}px)` }, { transform: "none" }], { duration: 340, easing: "cubic-bezier(.3, 1.2, .5, 1)" });
  }
}

export function open({ slot, table, rows, games, picks, render, mark, esc, code, favs, motionOn, colour, light, onClose }) {
  if (!document.getElementById("wi-css")) document.head.append(Object.assign(document.createElement("style"), { id: "wi-css", textContent: CSS }));
  const label = (g, t) => { const p = picks.get(String(g.id)); return p?.winner === t.abbr ? (p.ot ? "OT W" : "W") : ""; };
  const team = (g, t, cls) => `<button class="wi-t ${cls}${picks.get(String(g.id))?.winner === t.abbr ? " on" : ""}${light(t.abbr) ? " light" : ""}" style="--c:${esc(colour(t.abbr))}" data-g="${esc(g.id)}" data-t="${t.abbr}">${mark(t.abbr)}<span>${esc(code(t.abbr))}</span><em>${label(g, t)}</em></button>`;
  const fav = favs();
  function moves(next) {
    const was = new Map(rows.map(r => [r.abbr, r]));
    return next.filter(r => fav.has(r.abbr) && r.more !== undefined && place(r) !== place(was.get(r.abbr)))
      .map(r => `<div><b>${esc(code(r.abbr))}</b>: ${esc(place(was.get(r.abbr)))} → <b>${esc(place(r))}</b></div>`).join("");
  }
  function draw(next) {
    slot.innerHTML = `<div class="card wi"><div class="wi-h">What if?<span class="muted small" style="font-weight:400">Tap again for OT</span>
        <button class="linkish" id="wi-reset"${picks.size ? "" : " hidden"}>Reset</button><button class="linkish" id="wi-close">Close</button></div>
      ${games.map(g => `<div class="wi-g">${team(g, g.away, "a")}<span class="wi-at">at</span>${team(g, g.home, "h")}</div>`).join("") || `<div class="muted small">No games left to play today.</div>`}
      <div class="wi-moves">${moves(next)}</div></div>`;
  }
  function apply() {
    const next = project(rows, games, picks);
    glide(table, motionOn(), () => { table.innerHTML = render(next); });
    draw(next);
  }
  const off = new AbortController();
  slot.addEventListener("click", e => {
    if (e.target.id === "wi-close") { off.abort(); picks.clear(); glide(table, motionOn(), () => { table.innerHTML = render(rows); }); slot.innerHTML = ""; onClose(); return; }
    if (e.target.id === "wi-reset") { picks.clear(); apply(); return; }
    const b = e.target.closest("[data-g]");
    if (!b) return;
    // One team's button steps through: wins, wins in overtime, not decided.
    const now = picks.get(b.dataset.g), mine = now?.winner === b.dataset.t;
    if (!mine) picks.set(b.dataset.g, { winner: b.dataset.t, ot: false });
    else if (!now.ot) now.ot = true;
    else picks.delete(b.dataset.g);
    apply();
  }, { signal: off.signal });
  draw(project(rows, games, picks));
  if (picks.size) table.innerHTML = render(project(rows, games, picks));
}
