// The live dock: your teams' games on now, in a strip at the bottom of every page, so the score doesn't go away when
// you open the Wire. It lives outside #view, so nothing a page draws touches it.
// Loaded on demand once the first page is up (web/app.js); it costs a page nothing.
const LIVE_S = 10, IDLE_S = 90;
const KEEP_FINAL = 5 * 60000;   // a game you saw end stays this long: the last thing that happened shouldn't just vanish

let ctx, box, games = [], timer = 0, shown = "", goals = new Map(), sawLive = new Set(), endedAt = new Map(), queued = false;

const side = (g, s) => `<span>${ctx.esc(g[s].score ?? 0)}</span>`;
function status(g) {
  if (g.state === "final") return `Final${g.outcome && !["REG", "T"].includes(g.outcome) ? ` (${g.outcome})` : ""}`;
  return g.intermission ? `${g.period} INT` : `${g.period} ${g.clock || ""}`;
}
function item(g) {
  const a = g.away.abbr, h = g.home.abbr, T = ctx.teams(), ac = T[a]?.color || "#444", hc = T[h]?.color || "#444";
  return `<a class="dock-item" href="${ctx.gameHref(g)}" data-g="${ctx.esc(g.id)}" aria-label="${ctx.esc(`${ctx.teamName(a)} ${g.away.score ?? 0}, ${ctx.teamName(h)} ${g.home.score ?? 0}. Open the game`)}" style="--a:${ctx.esc(ctx.apart(ac, hc))};--h:${ctx.esc(hc)}">
    ${ctx.mark(a)}<div class="ms-mid"><b class="ms-sc">${side(g, "away")}<i>–</i>${side(g, "home")}</b><span class="ms-st">${ctx.esc(status(g))}</span></div>${ctx.mark(h)}</a>`;
}
// What's in the strip right now: not a game whose own page is open (the jumbotron has it), not one spoiler-free is hiding.
function current() {
  if (!ctx.dockOn()) return [];
  const now = Date.now();
  return games.filter(g => !ctx.spoilerHidden(g) && ctx.gameHref(g) !== location.hash
    && (g.state === "live" || now - (endedAt.get(g.id) ?? -Infinity) < KEEP_FINAL));
}
function draw() {
  const list = current(), ids = list.map(g => g.id).join();
  document.body.classList.toggle("has-dock", !!list.length);
  box.hidden = !list.length;
  box.classList.toggle("many", list.length > 1);
  if (ids !== shown) {
    const at = box.scrollLeft;
    box.innerHTML = list.map(item).join("");
    box.scrollLeft = at;
    shown = ids;
  } else for (const g of list) {   // same games: only the numbers, so a swipe in progress and the lamp both survive
    const el = box.querySelector(`[data-g="${CSS.escape(String(g.id))}"]`), [a, h] = el.querySelectorAll(".ms-sc span");
    if (a.textContent !== String(g.away.score ?? 0)) a.textContent = g.away.score ?? 0;
    if (h.textContent !== String(g.home.score ?? 0)) h.textContent = g.home.score ?? 0;
    const st = el.querySelector(".ms-st");
    if (st.textContent !== status(g)) st.textContent = status(g);
  }
  covered();
}
// Tonight shows these same games: the strip steps aside while the game's own card is on screen.
function covered() {
  const cards = current().map(g => document.querySelector(`#view a.hero-top[href="${ctx.gameHref(g)}"], #view a.body[href="${ctx.gameHref(g)}"]`));
  box.classList.toggle("aside", !!cards.length && cards.every(ctx.onScreen));
}
function onScroll() {
  if (queued || box.hidden) return;
  queued = true;
  requestAnimationFrame(() => { queued = false; covered(); });
}
// The goal lamp, and the horn if this device asked for it. A first look at a game only records it, so opening the app
// mid-game never celebrates a goal scored an hour ago.
function celebrate(g) {
  const was = goals.get(g.id), fav = ctx.favs();
  const ours = (fav.has(g.away.abbr) ? g.away.score ?? 0 : 0) + (fav.has(g.home.abbr) ? g.home.score ?? 0 : 0);
  const total = (g.away.score ?? 0) + (g.home.score ?? 0);
  goals.set(g.id, { ours, total });
  if (!was || ctx.spoilerHidden(g)) return;
  if (total > was.total && ctx.motionOn()) {
    const el = box.querySelector(`[data-g="${CSS.escape(String(g.id))}"] .ms-sc`);
    if (el) ctx.lamp(el);
  }
  if (ours > was.ours && ctx.hornOn()) import(`./horn.js${ctx.V}`).then(m => m.play()).catch(() => {});
}
async function tick() {
  clearTimeout(timer);
  if (document.hidden) return;   // visibilitychange starts it again
  let live = false;
  if (ctx.favs().size && (ctx.dockOn() || ctx.hornOn() || ctx.dimOn())) {   // hidden, it still listens for the horn and the lights
    try {
      games = (await ctx.api("/api/live")).games;
      live = games.some(g => g.state === "live");
      ctx.onLive(games.filter(g => g.state === "live" && !ctx.spoilerHidden(g)));   // the line under the app's name
      for (const g of games) {
        if (g.state === "live") sawLive.add(g.id);
        else if (sawLive.has(g.id) && !endedAt.has(g.id)) endedAt.set(g.id, Date.now());
      }
      draw();
      games.forEach(celebrate);
    } catch { /* the next one will do */ }
  } else {
    goals.clear();
    games = [];
    ctx.onLive([]);
    if (shown) draw();
  }
  const again = endedAt.size && [...endedAt.values()].some(t => Date.now() - t < KEEP_FINAL);
  clearTimeout(timer);   // a refresh may have landed while this one waited
  timer = setTimeout(tick, (live || again ? LIVE_S : IDLE_S) * 1000);
}

export function start(context) {
  ctx = context;
  box = Object.assign(document.createElement("div"), { className: "dock", hidden: true });
  box.setAttribute("aria-label", "Your teams' games on now");
  box.setAttribute("role", "region");
  document.body.append(box);
  box.inert = ctx.menuIsOpen();   // arrived while the menu was open: it stays out of reach until that closes
  addEventListener("scroll", onScroll, { passive: true });
  // After the page change, not during it: a tapped strip grows into the game's jumbotron, and has to still be there for that.
  addEventListener("hashchange", () => setTimeout(() => { if (games.length) draw(); }, 360));
  // Coming back counts as a first look too: the horn isn't for a goal scored while the phone was in a pocket.
  document.addEventListener("visibilitychange", () => { if (document.hidden) goals.clear(); else tick(); });
  if (ctx.hornOn()) import(`./horn.js${ctx.V}`).then(m => m.arm()).catch(() => {});
  tick();
}
export const refresh = () => { if (box) tick(); };
