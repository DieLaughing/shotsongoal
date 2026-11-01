// Replay: drag the puck along the game and the shot map fills in as it happened, or press play to watch it in about 20
// seconds. Loaded on demand by the game page (web/app.js loadReplay), and it needs nothing the page doesn't already have.
const PLAY_MS = 20000;   // the whole game, not counting the beat on each goal
const GOAL_BEAT = 600;
const CSS = `
.rp-burst { fill: none; stroke: var(--accent); stroke-width: 1.4; pointer-events: none; }
.rp-now { fill: none; stroke: var(--text); stroke-width: .8; pointer-events: none; }`;

const bound = new WeakMap();

// Called after every draw of the game page: `card` is the shot map's card, `timeline` comes from timeline() in web/app.js.
export function attach(card, timeline, ctx) {
  if (!document.getElementById("rp-css")) document.head.append(Object.assign(document.createElement("style"), { id: "rp-css", textContent: CSS }));
  let r = bound.get(card);
  if (!r) bound.set(card, r = replay(card, ctx));
  r.load(timeline);
}

function replay(card, { lamp, motionOn, engaged, esc, clipFor }) {
  const range = card.querySelector(".rp input"), play = card.querySelector(".rp button"), read = card.querySelector(".rp-read");
  const rink = card.querySelector(".rink");
  const now = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  now.setAttribute("class", "rp-now"); now.setAttribute("r", "4"); now.style.display = "none";
  let tl, order = [], shown = 0, frame = 0, wait = 0, playing = false;
  play.hidden = !motionOn();

  const score = i => { let a = 0, h = 0;
    for (const s of order.slice(0, i)) if (s.shot.kind === "goal") s.shot.team === tl.home ? h++ : a++;
    return [a, h]; };
  const stamp = t => { const p = tl.periods.findLast(x => x.from <= t), left = t - p.from;
    return `${p.name} ${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`; };

  // The goal line is only rewritten when it changes: rebuilt on every frame, its Watch link couldn't be tapped.
  let goalLine = null;
  function say(t) {
    if (t >= tl.end) { read.innerHTML = tl.endText; goalLine = null; return; }
    const [a, h] = score(shown), last = order.slice(0, shown).findLast(s => s.shot.kind === "goal" && t - s.t < 75);
    const line = `<span>${t ? stamp(t) : "Puck drop"}</span><b><small>${esc(tl.awayCode)}</small> ${a}–${h} <small>${esc(tl.homeCode)}</small></b>`;
    const goal = last ? `<span class="rp-goal-by">🚨 ${esc(last.shot.shooter)} ${clipFor?.(last.shot) ?? ""}</span>` : "";
    if (goal === goalLine) { read.firstElementChild.innerHTML = line; return; }
    read.innerHTML = `<div class="rp-line">${line}</div>${goal}`;
    goalLine = goal;
  }
  // Shots are in time order, so a move only touches the dots between the old spot and the new one.
  function seek(t, celebrate) {
    const next = order.findIndex(s => s.t > t), upto = next < 0 || t >= tl.end ? order.length : next;
    for (let i = shown; i < upto; i++) {
      order[i].el.style.display = "";
      if (celebrate && order[i].shot.kind === "goal" && order[i].t <= tl.end) burst(order[i].shot);
    }
    for (let i = upto; i < shown; i++) order[i].el.style.display = "none";
    shown = upto;
    range.style.setProperty("--p", `${t / tl.end * 100}%`);
    const at = order[shown - 1]?.shot;
    if (at && t < tl.end) { now.setAttribute("cx", at.x); now.setAttribute("cy", -at.y); now.style.display = ""; } else now.style.display = "none";
    say(t);
  }
  function burst(shot) {
    const ring = now.cloneNode(); ring.setAttribute("class", "rp-burst"); ring.style.display = "";
    ring.setAttribute("cx", shot.x); ring.setAttribute("cy", -shot.y); ring.style.transformOrigin = `${shot.x}px ${-shot.y}px`;
    rink.append(ring);
    ring.animate([{ transform: "scale(.4)", opacity: 1 }, { transform: "scale(4)", opacity: 0 }], { duration: 520, easing: "ease-out" }).finished.finally(() => ring.remove());
    lamp(read);
  }
  function stop(release) {
    playing = false; cancelAnimationFrame(frame); clearTimeout(wait);
    play.textContent = "▶"; play.setAttribute("aria-label", "Play the game back");
    if (release) { now.remove(); engaged(false); }
  }
  function start() {
    engaged(true); rink.append(now);
    if (+range.value >= tl.end) { range.value = 0; order.forEach(s => { s.el.style.display = "none"; }); shown = 0; }
    playing = true; play.textContent = "❚❚"; play.setAttribute("aria-label", "Pause");
    let last = performance.now();
    const speed = tl.end / PLAY_MS;
    const tick = time => {
      if (!range.isConnected) return stop(true);
      const t = Math.min(tl.end, +range.value + Math.max(1, Math.round((time - last) * speed)));
      last = time;
      const goal = order.slice(shown).find(s => s.t <= t && s.shot.kind === "goal");
      range.value = t; seek(t, true);
      if (t >= tl.end) return stop(true);
      if (goal) wait = setTimeout(() => { last = performance.now(); frame = requestAnimationFrame(tick); }, GOAL_BEAT);
      else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
  }

  range.addEventListener("input", () => {
    stop();
    const t = +range.value;
    if (t >= tl.end) { seek(t); stop(true); return; }
    engaged(true); rink.append(now);
    seek(t);
  });
  play.addEventListener("click", () => (playing ? stop() : start()));
  read.addEventListener("click", e => { if (e.target.closest("[data-clip]")) stop(); });   // watching the goal pauses the game
  card.endReplay = () => { range.value = tl.end; seek(tl.end); stop(true); };   // the period buttons take the map back

  return {
    load(timeline) {
      tl = timeline;
      const list = [...rink.querySelectorAll("[data-i]")].map(el => ({ el, shot: tl.shots[+el.dataset.i], t: tl.at(tl.shots[+el.dataset.i]) }));
      order = list.sort((x, y) => x.t - y.t);
      range.max = tl.end;
      shown = order.length;
      if (+range.value >= tl.end || range.value === "") range.value = tl.end;
      seek(+range.value);
    },
  };
}
