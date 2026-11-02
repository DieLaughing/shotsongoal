// Game story: a final told goal by goal. Each swipe is one moment, and the jumbotron and the rink above stay put and catch up,
// so a game you missed plays out in order. Spoiler-free is the point: one moment fills the screen, there's no scrollbar or
// count of what's left, and a clip's Next button stops at the goal you've reached. Loaded on demand (web/app.js openStory).
// It sits on <body>, so a live refresh can't touch it, with its own step in the history so the back gesture closes it.
const CSS = `
.st { position: fixed; inset: 0; z-index: 25; display: flex; flex-direction: column; padding: env(safe-area-inset-top, 0px) 0 env(safe-area-inset-bottom, 0px);
  background: #07090d; color: #fff; outline: 0; }
.st-in { flex: 1; min-height: 0; width: 100%; max-width: 620px; margin: 0 auto; display: flex; flex-direction: column; }
.st-bar { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px 6px 16px; }
.st-title { font: 800 18px/1 Arena, Score, system-ui, sans-serif; text-transform: uppercase; letter-spacing: .03em; color: rgba(255, 255, 255, .72); }
.st-x { width: 40px; height: 40px; border: 0; border-radius: 50%; background: rgba(255, 255, 255, .14); color: #fff; font-size: 16px; cursor: pointer; }
.st-bug { position: relative; overflow: hidden; display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 14px; padding: 8px 16px;
  background:
    radial-gradient(ellipse 150px 120% at 50% 50%, rgba(8, 10, 14, .78) 30%, transparent 100%),
    linear-gradient(101deg, color-mix(in srgb, var(--a) 68%, #0a0d12) 50%, color-mix(in srgb, var(--h) 68%, #0a0d12) 50%); }
.st-bug > .mark:first-child { justify-self: end; }
.st-mid { display: grid; justify-items: center; }
.st-sc { font: 800 54px/1 Score, system-ui, sans-serif; font-variant-numeric: tabular-nums; display: grid; grid-template-columns: 1fr auto 1fr; gap: 6px; }
.st-sc b { font-weight: inherit; display: block; justify-self: end; }
.st-sc b:last-child { justify-self: start; }
.st-sc i { font-style: normal; font-size: .62em; opacity: .55; align-self: center; }
.st-when { font-size: 12.5px; font-weight: 600; color: rgba(255, 255, 255, .8); min-height: 1.3em; }
.st-rink { flex: none; padding: 8px 16px 0; --text: #fff; --muted: rgba(255, 255, 255, .55); --border: rgba(255, 255, 255, .2); --red: #ff6b7a; }
.st-rink svg { display: block; width: 100%; max-height: 24dvh; }
.st-beats { flex: 1; min-height: 0; overflow-y: auto; scroll-snap-type: y mandatory; scrollbar-width: none; overscroll-behavior: contain; outline: 0; }
.st-beats::-webkit-scrollbar { display: none; }
.st-beat { height: 100%; scroll-snap-align: start; scroll-snap-stop: always; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; padding: 12px 20px; text-align: center; }
.st-k { font-size: 13px; font-weight: 650; color: rgba(255, 255, 255, .72); }
.st-big { font: 800 44px/1 Arena, Score, system-ui, sans-serif; text-transform: uppercase; letter-spacing: .012em; overflow-wrap: anywhere; }
.st-beat .mark.big { width: 64px; height: 44px; }
.st-note { font-size: 14px; color: rgba(255, 255, 255, .78); max-width: 34em; }
.st-tag { display: inline-block; padding: 1px 7px; border-radius: 6px; background: rgba(255, 255, 255, .14); font-size: 12px; font-weight: 700; }
.st-acts { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-top: 6px; }
.st-acts .clipbtn, .st-btn { min-height: 40px; padding: 0 14px; display: inline-flex; align-items: center; gap: 6px; border: 1px solid rgba(255, 255, 255, .22); border-radius: 10px;
  background: rgba(255, 255, 255, .08); color: #fff; font: inherit; font-size: 14px; font-weight: 650; text-decoration: none; cursor: pointer; }
.st-acts .clip-ico { color: inherit; }
.st-hint { margin-top: 14px; font-size: 12.5px; color: rgba(255, 255, 255, .6); }
.st-stars { display: grid; gap: 3px; font-size: 14px; color: rgba(255, 255, 255, .85); }
@media (max-height: 560px) { .st-rink { display: none; } .st-sc { font-size: 38px; } .st-big { font-size: 34px; } }`;

export function open({ d, g, hidden, reel, films, seen, mark, esc, lamp, motionOn, rink, timeline, clockOf, clipLink, openClip }) {
  if (!document.getElementById("st-css")) document.head.append(Object.assign(document.createElement("style"), { id: "st-css", textContent: CSS }));
  const a = g.away.abbr, h = g.home.abbr, tl = d.shotmap?.length >= 10 ? timeline(d.shotmap, a, h, g) : null;
  const stamp = (name, secs) => { const p = tl?.periods.find(x => x.name === name); return p ? p.from + secs : null; };
  const ending = g.outcome && !["REG", "T"].includes(g.outcome) ? ` (${g.outcome})` : "";

  // The game as a list of moments. Each knows the score and the game time once it's on screen.
  // A shootout isn't on the game clock: its moments keep the rink as it was.
  let score = [0, 0], clock = -1;
  const beats = [{ kind: "start", score, at: clock, when: "Puck drop" }];
  for (const p of d.scoring) {
    for (const x of p.goals) {
      score = [x.away, x.home];
      clock = stamp(p.period, clockOf(x)) ?? clock;
      beats.push({ kind: "goal", x, period: p.period, score, at: clock, when: `${p.period} ${x.time}` });
    }
    const shots = d.shots?.find(s => s.period === p.period), length = tl?.periods.find(q => q.name === p.period);
    if (length) clock = length.from + length.len - 1;
    if (p.period !== "SO") beats.push({ kind: "break", period: p.period, shots, score, at: clock, when: `End of the ${p.period}` });
  }
  beats.at(-1).kind === "break" && beats.pop();    // the last period's end is the final
  beats.push({ kind: "final", score: [g.away.score ?? 0, g.home.score ?? 0], at: Infinity, when: `Final${ending}` });

  const goalLine = b => {
    const x = b.x, tags = [x.strength !== "EV" ? x.strength : "", x.modifier === "empty-net" ? "EN" : ""].filter(Boolean).map(t => `<span class="st-tag">${esc(t)}</span>`).join(" ");
    const help = x.assists?.length ? `From ${x.assists.map(y => esc(y.name)).join(" and ")}` : "Unassisted";
    const clip = reel.find(c => c.url === x.clip);
    return `<div class="st-k">${esc(b.when)}</div>${mark(x.team, true)}<div class="st-big">${esc(x.scorer)}</div>
      <div class="st-note">${x.total ? `Goal ${esc(x.total)} · ` : ""}${help} ${tags}</div>
      ${clip ? `<div class="st-acts">${clipLink(clip.url, clip.id)}</div>` : ""}`;
  };
  const beat = (b, i) => `<section class="st-beat" data-i="${i}">${
    b.kind === "start" ? `<div class="st-k">${esc(g.venue || "Puck drop")}</div><div class="st-big">Puck drop</div><div class="st-hint">Swipe up to play the game out, one moment at a time.</div>`
    : b.kind === "goal" ? goalLine(b)
    : b.kind === "break" ? `<div class="st-k">Period over</div><div class="st-big">End of the ${esc(b.period)}</div>${b.shots ? `<div class="st-note">Shots in the period: ${esc(b.shots.away)}–${esc(b.shots.home)}</div>` : ""}`
    : `<div class="st-k">That's the game</div><div class="st-big">Final${esc(ending)}</div>
       ${d.stars?.length ? `<div class="st-stars">${d.stars.map(s => `<div>${"★".repeat(s.star)} ${esc(s.name)}</div>`).join("")}</div>` : ""}
       <div class="st-acts">${films.map(f => `<button class="st-btn" data-film="${esc(f.id)}"><span aria-hidden="true">▶</span> ${esc(f.who)}</button>`).join("")}
         ${hidden ? `<button class="st-btn" data-seen>I've seen it</button>` : ""}<button class="st-btn" data-close>Close</button></div>`
  }</section>`;

  const root = Object.assign(document.createElement("div"), { className: "st", tabIndex: -1 });
  root.setAttribute("role", "dialog"); root.setAttribute("aria-modal", "true"); root.setAttribute("aria-label", "Game story");
  root.innerHTML = `<div class="st-in"><div class="st-bar"><span class="st-title">Game story</span><button class="st-x" aria-label="Close">✕</button></div>
    <div class="st-bug" style="--a:${esc(g.paints.a)};--h:${esc(g.paints.h)}">${mark(a)}<div class="st-mid"><div class="st-sc"><b data-side="0">0</b><i>–</i><b data-side="1">0</b></div><div class="st-when" aria-live="polite"></div></div>${mark(h)}</div>
    ${tl ? `<div class="st-rink">${rink(d.shotmap)}</div>` : ""}
    <div class="st-beats" tabindex="0">${beats.map(beat).join("")}</div></div>`;

  const nums = [...root.querySelectorAll("[data-side]")], when = root.querySelector(".st-when"), list = root.querySelector(".st-beats");
  const dots = tl ? [...root.querySelectorAll(".st-rink [data-i]")].map(el => ({ el, t: tl.at(tl.shots[+el.dataset.i]) })) : [];
  let now = -1;
  function go(i) {
    if (i === now) return;
    const b = beats[i], forward = i > now;
    now = i;
    when.textContent = b.when;
    nums.forEach((el, side) => {
      if (el.textContent === String(b.score[side])) return;
      el.textContent = b.score[side];
      if (forward && motionOn()) lamp(el);
    });
    for (const dot of dots) dot.el.style.display = dot.t <= b.at ? "" : "none";
  }

  const scroller = document.documentElement, overflow = scroller.style.overflow, from = document.activeElement, behind = [...document.body.children];
  function shut() {
    if (!root.isConnected) return;
    watch.disconnect();
    root.remove();
    scroller.style.overflow = overflow;
    behind.forEach(el => { el.inert = false; });
    removeEventListener("popstate", onPop); removeEventListener("hashchange", shut); removeEventListener("keydown", key);
    from?.focus?.({ preventScroll: true });
  }
  const close = () => history.back();
  // A clip's theatre has its own history step: coming back from it lands here. It un-inerts what's behind as it closes,
  // on this same event, so that has to be put back after it.
  const onPop = () => { if (history.state?.story) setTimeout(() => behind.forEach(el => { el.inert = true; })); else shut(); };
  const key = e => { if (e.key === "Escape" && !document.querySelector(".clipview")) close(); };
  const watch = new IntersectionObserver(entries => { for (const e of entries) if (e.isIntersecting) go(+e.target.dataset.i); }, { root: list, threshold: .6 });

  root.addEventListener("click", e => {
    const t = e.target, clip = t.closest("[data-clip]"), film = t.closest("[data-film]");
    if (t.closest(".st-x, [data-close]")) close();
    else if (t.closest("[data-seen]")) { shut(); history.back(); seen(); }
    else if (film) openClip(film.dataset.film, films, "Next");
    else if (clip && !(e.metaKey || e.ctrlKey || e.shiftKey)) {
      e.preventDefault();
      // Never past where you've got to: Next goal stops here.
      const at = reel.findIndex(c => c.id === clip.dataset.clip);
      openClip(clip.dataset.clip, reel.slice(0, at + 1));
    }
  });
  history.pushState({ story: true }, "");
  addEventListener("popstate", onPop); addEventListener("hashchange", shut); addEventListener("keydown", key);
  scroller.style.overflow = "hidden";
  behind.forEach(el => { el.inert = true; });
  document.body.append(root);
  go(0);
  root.querySelectorAll(".st-beat").forEach(el => watch.observe(el));
  if (motionOn()) root.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 180, easing: "ease-out" });
  list.focus({ preventScroll: true });
}
