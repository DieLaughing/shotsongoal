// Flick your picks: Pick'em one game at a time. Flick the puck at a team (or tap its side) and the next game comes up.
// Loaded on demand from the Pick'em page (web/app.js); saves through the same POST /api/pickem as the list.
const CSS = `
.flick { position: fixed; inset: 0; z-index: 30; display: flex; flex-direction: column; color: #fff; background: #0a0d12;
  padding: env(safe-area-inset-top, 0px) 0 env(safe-area-inset-bottom, 0px); touch-action: none; user-select: none; -webkit-user-select: none; outline: 0; }
.fk-top { display: flex; align-items: center; gap: 12px; padding: 12px 16px; }
.fk-n { font: 800 22px/1 Score, system-ui, sans-serif; font-variant-numeric: tabular-nums; }
.fk-bar { flex: 1; height: 4px; border-radius: 2px; background: rgba(255, 255, 255, .16); overflow: hidden; }
.fk-bar i { display: block; height: 100%; background: #fff; border-radius: 2px; transform-origin: 0 50%; transition: transform 220ms ease; }
.fk-x { width: 36px; height: 36px; border: 0; border-radius: 50%; background: rgba(255, 255, 255, .12); color: #fff; font-size: 15px; cursor: pointer; }
.fk-ice { position: relative; flex: 1; min-height: 0; display: grid; grid-template-columns: 1fr 1fr; overflow: hidden; }
.fk-ice::before { content: ""; position: absolute; top: 0; bottom: 0; left: 50%; width: 4px; margin-left: -2px; z-index: 1; pointer-events: none; background: #e8112d; box-shadow: 0 0 10px rgba(232, 17, 45, .6); }
.fk-side { position: relative; border: 0; color: inherit; font: inherit; padding: 12px 10px 34%; cursor: pointer; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; min-width: 0;
  transition: opacity 140ms ease; }
.fk-side.a { background: linear-gradient(180deg, color-mix(in srgb, var(--a) 68%, #0a0d12), color-mix(in srgb, var(--a) 38%, #0a0d12)); }
.fk-side.h { background: linear-gradient(180deg, color-mix(in srgb, var(--h) 68%, #0a0d12), color-mix(in srgb, var(--h) 38%, #0a0d12)); }
.fk-ice.lean-a .fk-side.h, .fk-ice.lean-h .fk-side.a { opacity: .38; }
.fk-side .mark { width: min(30vw, 150px); height: min(24vw, 120px); font-size: 28px; border-radius: 16px; }
.fk-nm { font-weight: 800; font-size: 19px; line-height: 1.15; text-align: center; overflow-wrap: anywhere; }
.fk-rec { font-size: 12.5px; opacity: .8; font-weight: 600; }
.fk-pct { font: 800 34px/1 Score, system-ui, sans-serif; }
.fk-dog { font-size: 12px; font-weight: 750; padding: 3px 8px; border-radius: 7px; background: #fff; color: #111; }
.fk-when { position: absolute; z-index: 2; left: 0; right: 0; top: 12px; text-align: center; font: 800 25px/1 Score, system-ui, sans-serif; pointer-events: none; text-shadow: 0 1px 8px rgba(0, 0, 0, .5); }
.fk-puck { position: absolute; z-index: 2; left: 50%; bottom: 13%; width: 84px; height: 56px; margin-left: -42px; border-radius: 50%; cursor: grab; will-change: transform;
  background: radial-gradient(ellipse at 50% 34%, #51565f 0 36%, #14161b 72%); box-shadow: 0 8px 14px rgba(0, 0, 0, .55), 0 0 0 1.5px rgba(255, 255, 255, .28); }
.fk-hint { position: absolute; z-index: 2; left: 0; right: 0; bottom: calc(13% - 30px); text-align: center; font-size: 12.5px; font-weight: 600; opacity: .85; pointer-events: none; }
.fk-foot { display: flex; gap: 10px; padding: 12px 16px; }
.fk-foot button { flex: 1; min-height: 46px; border-radius: 12px; border: 1px solid rgba(255, 255, 255, .22); background: rgba(255, 255, 255, .08); color: #fff; font: inherit; font-weight: 700; cursor: pointer; }
.fk-foot .on { background: #fff; color: #111; }
.fk-done { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; padding: 24px; text-align: center; overflow: auto; touch-action: pan-y; }
.fk-done h2 { font: 800 30px/1.1 system-ui, sans-serif; color: #fff; text-transform: none; letter-spacing: 0; margin: 0; }
.fk-list { display: grid; gap: 8px; width: min(320px, 100%); }
.fk-list div { display: flex; align-items: center; gap: 10px; font-weight: 650; text-align: left; }
.fk-list b { margin-left: auto; color: #ffd76a; }
@media (min-width: 700px) { .fk-side .mark { width: 170px; height: 130px; } .flick { inset: 4vh max(16px, calc(50vw - 380px)); border-radius: 20px; overflow: hidden; box-shadow: 0 20px 80px rgba(0, 0, 0, .6); } }`;

const FLICK_AT = 64;        // px of drag that counts as a pick,
const FLICK_MIN = 24;       // or this much, if it was still
const FLICK_SPEED = .55;    // moving this fast (px/ms)
const FLICK_FRESH = 80;     // within this long (ms) of letting go

export function open({ games, mark, esc, name, colour, record, oddsFor, send, pool, lockAt, motionOn, done }) {
  if (!document.getElementById("fk-css")) document.head.append(Object.assign(document.createElement("style"), { id: "fk-css", textContent: CSS }));
  const root = Object.assign(document.createElement("div"), { className: "flick", tabIndex: -1 });
  root.setAttribute("role", "dialog"); root.setAttribute("aria-modal", "true"); root.setAttribute("aria-label", "Flick your picks");
  let at = 0, lock = false, puck = null, ice = null, busy = false;
  const made = [];
  const scroller = document.documentElement, overflow = scroller.style.overflow;
  scroller.style.overflow = "hidden";

  function close() {
    root.remove(); scroller.style.overflow = overflow;
    removeEventListener("hashchange", close); removeEventListener("keydown", key);
    done();
  }
  function key(e) {
    if (e.key === "Escape") close();
    else if (e.key === "ArrowLeft") pick("away");
    else if (e.key === "ArrowRight") pick("home");
  }

  function draw() {
    const g = games[at];
    if (!g) return finish();
    lock = false;
    const a = g.away.abbr, h = g.home.abbr, o = oddsFor(g), dog = t => g.bonus && o?.fav && o.fav !== t.abbr;
    // The page's lock, or one made in this run. One whose game has started can't move (the server would refuse).
    const stuck = lockAt(g) === "stuck", moves = lockAt(g) === "moves" || made.some(m => m.lock && m.pool === pool(g));
    const side = (t, cls) => `<button class="fk-side ${cls}" data-side="${cls === "a" ? "away" : "home"}" aria-label="Pick ${esc(name(t.abbr))}">
        ${mark(t.abbr)}<span class="fk-nm">${esc(name(t.abbr))}</span>${record(t) ? `<span class="fk-rec">${esc(record(t))}</span>` : ""}
        ${o?.away_pct ? `<span class="fk-pct">${t === g.home ? o.home_pct : o.away_pct}%</span>` : ""}${dog(t) ? `<span class="fk-dog">2× if right</span>` : ""}</button>`;
    root.innerHTML = `<div class="fk-top"><span class="fk-n">${at + 1}/${games.length}</span><div class="fk-bar"><i style="transform:scaleX(${at / games.length})"></i></div><button class="fk-x" aria-label="Close">✕</button></div>
      <div class="fk-ice" style="--a:${esc(colour(a, h))};--h:${esc(colour(h))}">${side(g.away, "a")}${side(g.home, "h")}
        <div class="fk-when">${esc(g.when)}</div><div class="fk-puck" role="presentation"></div>
        ${at ? "" : `<div class="fk-hint">Flick the puck at your pick</div>`}</div>
      <div class="fk-foot">${stuck ? "" : `<button class="fk-lock" aria-pressed="false">★ ${moves ? "Move my lock here" : "Lock of the night"}</button>`}<button class="fk-skip">Skip</button></div>`;
    ice = root.querySelector(".fk-ice"); puck = root.querySelector(".fk-puck");
    root.querySelector(".fk-x").onclick = close;
    root.querySelector(".fk-skip").onclick = () => { if (!busy) { at++; draw(); } };
    const star = root.querySelector(".fk-lock");
    if (star) star.onclick = e => { lock = !lock; e.currentTarget.classList.toggle("on", lock); e.currentTarget.setAttribute("aria-pressed", lock); };
    root.querySelectorAll(".fk-side").forEach(b => { b.onclick = () => pick(b.dataset.side); });
    if (motionOn()) ice.animate([{ opacity: .25 }, { opacity: 1 }], { duration: 200, easing: "ease-out" });
    grab();
  }

  function grab() {
    let x0 = 0, dx = 0, lastX = 0, lastT = 0, speed = 0, held = false;
    puck.addEventListener("pointerdown", e => {
      if (busy) return;
      held = true; x0 = lastX = e.clientX; lastT = e.timeStamp; dx = speed = 0;
      puck.setPointerCapture(e.pointerId); e.preventDefault();
    });
    puck.addEventListener("pointermove", e => {
      if (!held) return;
      dx = e.clientX - x0;
      speed = (e.clientX - lastX) / Math.max(1, e.timeStamp - lastT); lastX = e.clientX; lastT = e.timeStamp;
      puck.style.transform = `translateX(${Math.round(dx)}px)`;
      ice.classList.toggle("lean-a", dx < -18); ice.classList.toggle("lean-h", dx > 18);
    });
    const letGo = e => {
      if (!held) return;
      held = false;
      const moving = e.timeStamp - lastT < FLICK_FRESH && Math.abs(speed) > FLICK_SPEED && Math.sign(speed) === Math.sign(dx);
      if (e.type === "pointerup" && (Math.abs(dx) > FLICK_AT || (Math.abs(dx) > FLICK_MIN && moving))) return pick(dx < 0 ? "away" : "home");
      ice.classList.remove("lean-a", "lean-h");
      if (motionOn()) puck.animate([{ transform: `translateX(${Math.round(dx)}px)` }, { transform: "none" }], { duration: 260, easing: "cubic-bezier(.3, 1.4, .5, 1)" });
      puck.style.transform = "";
    };
    puck.addEventListener("pointerup", letGo);
    puck.addEventListener("pointercancel", letGo);
  }

  async function pick(sideName) {
    const g = games[at];
    if (busy || !g) return;
    busy = true;
    const team = g[sideName].abbr;
    if (lock) made.forEach(m => { if (m.pool === pool(g)) m.lock = false; });   // one lock a night
    const entry = { team, lock, pool: pool(g), saved: true };
    entry.done = send(g, team, lock).then(got => { entry.saved = !!got; entry.lock = entry.lock && got === "locked"; });
    made.push(entry);
    ice.classList.remove("lean-a", "lean-h");
    ice.classList.add(sideName === "away" ? "lean-a" : "lean-h");
    if (motionOn()) {
      const target = root.querySelector(`.fk-side.${sideName === "away" ? "a" : "h"} .mark`).getBoundingClientRect(), from = puck.getBoundingClientRect();
      const x = Math.round(target.x + target.width / 2 - from.x - from.width / 2), y = Math.round(target.y + target.height / 2 - from.y - from.height / 2);
      const start = new DOMMatrix(getComputedStyle(puck).transform).m41;
      await puck.animate([{ transform: `translate(${Math.round(start)}px, 0)` }, { transform: `translate(${Math.round(start + x)}px, ${y}px)`, opacity: .9, offset: .85 }, { transform: `translate(${Math.round(start + x)}px, ${y}px)`, opacity: 0 }],
        { duration: 260, easing: "cubic-bezier(.2, .8, .4, 1)", fill: "forwards" }).finished.catch(() => {});
    }
    busy = false;
    at++; draw();
  }

  async function finish() {
    root.innerHTML = "";
    await Promise.all(made.map(m => m.done));
    const list = made.filter(m => m.saved), n = list.length;
    root.innerHTML = `<div class="fk-done"><h2>${n ? `${n} pick${n > 1 ? "s" : ""} in` : "Nothing picked"}</h2>
      <div class="fk-list">${list.map(p => `<div>${mark(p.team)}<span>${esc(name(p.team))}</span>${p.lock ? "<b>★ Lock</b>" : ""}</div>`).join("")}</div></div>
      <div class="fk-foot"><button class="fk-close on">Done</button></div>`;
    root.querySelector(".fk-close").onclick = close;
    root.querySelector(".fk-close").focus();
  }

  addEventListener("hashchange", close); addEventListener("keydown", key);
  document.body.append(root);
  draw();
  root.focus();
}
