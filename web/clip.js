// Goal clips in the app: a theatre over the page playing the clip in the NHL's own player, ads and all. Loaded on the
// first tap (web/app.js openClip); nothing from the player reaches a page until then. It sits on <body>, so a live
// refresh can't touch it. The stream is never played directly: the league's player is what it publishes, whole.
const PLAYER = "https://players.brightcove.net/6415718365001/default_default/index.html";
const CSS = `
.clipview { position: fixed; inset: 0; z-index: 30; display: flex; align-items: center; justify-content: center; padding: env(safe-area-inset-top, 0px) 0 env(safe-area-inset-bottom, 0px); background: rgba(5, 7, 10, .975); color: #fff; outline: 0; }
.cv-box { width: min(100%, 960px, calc((100dvh - 150px) * 16 / 9)); min-width: min(100%, 320px); }
.cv-top { display: flex; align-items: center; gap: 10px; padding: 8px 14px; min-width: 0; background: color-mix(in srgb, var(--c) 68%, #0a0d12); }
.cv-who { min-width: 0; line-height: 1.25; }
.cv-who b { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cv-who span { font-size: 12.5px; color: rgba(255, 255, 255, .72); }
.cv-x { flex: none; width: 40px; height: 40px; margin-left: auto; border: 0; border-radius: 50%; background: rgba(255, 255, 255, .14); color: #fff; font-size: 16px; cursor: pointer; }
.cv-frame { aspect-ratio: 16 / 9; background: #000; }
.cv-frame iframe { display: block; width: 100%; height: 100%; border: 0; }
.cv-foot { display: flex; align-items: center; gap: 8px; padding: 10px 14px; }
.cv-foot button { min-height: 40px; padding: 0 14px; border: 1px solid rgba(255, 255, 255, .22); border-radius: 10px; background: rgba(255, 255, 255, .08); color: #fff; font: inherit; font-size: 13.5px; font-weight: 650; cursor: pointer; }
.cv-foot button:disabled { opacity: .35; cursor: default; }
.cv-foot a { margin-left: auto; font-size: 12.5px; color: rgba(255, 255, 255, .72); }
/* A phone on its side: the video takes the height, everything else a column beside it. */
@media (max-height: 500px) {
  .cv-box { width: 100%; display: grid; grid-template-columns: minmax(0, 1fr) 176px; grid-template-rows: auto 1fr; }
  .cv-frame { grid-row: 1 / 3; justify-self: center; height: 100dvh; max-width: 100%; }
  .cv-foot { flex-direction: column; align-items: stretch; justify-content: flex-end; }
  .cv-foot a { margin: 4px 0 0; }
}`;

export function open({ reel, at, mark, esc, motionOn, colour }) {
  if (!document.getElementById("cv-css")) document.head.append(Object.assign(document.createElement("style"), { id: "cv-css", textContent: CSS }));
  const root = Object.assign(document.createElement("div"), { className: "clipview", tabIndex: -1 });
  root.setAttribute("role", "dialog"); root.setAttribute("aria-modal", "true"); root.setAttribute("aria-label", "Goal clip");
  const scroller = document.documentElement, overflow = scroller.style.overflow;
  const from = document.activeElement, behind = [...document.body.children];
  scroller.style.overflow = "hidden";
  behind.forEach(el => { el.inert = true; });

  function shut() {
    if (!root.isConnected) return;
    root.remove();   // takes the player and its sound with it
    scroller.style.overflow = overflow;
    behind.forEach(el => { el.inert = false; });
    removeEventListener("popstate", shut); removeEventListener("hashchange", shut); removeEventListener("keydown", key);
    from?.focus?.({ preventScroll: true });
  }
  // The theatre has its own step in the history, so the phone's back gesture closes it instead of leaving the game.
  const close = () => history.back();
  function go(step) {
    if (!reel[at + step]) return;
    at += step; draw();
    const btn = root.querySelector(step > 0 ? "#cv-next" : "#cv-prev");
    (btn && !btn.disabled ? btn : root).focus();
  }
  function key(e) {
    if (e.key === "Escape") close();
    else if (e.key === "ArrowLeft") go(-1);
    else if (e.key === "ArrowRight") go(1);
  }
  function draw() {
    const c = reel[at];
    root.innerHTML = `<div class="cv-box"><div class="cv-top" style="--c:${esc(colour(c.team))}">${mark(c.team)}<div class="cv-who"><b>${esc(c.who)}</b><span>${esc(c.when)} · ${esc(c.score)}</span></div>
        <button class="cv-x" aria-label="Close">✕</button></div>
      <div class="cv-frame"><iframe title="Goal by ${esc(c.who)}" src="${PLAYER}?videoId=${esc(c.id)}&autoplay=any" allow="autoplay; fullscreen; picture-in-picture; encrypted-media" allowfullscreen></iframe></div>
      <div class="cv-foot">${reel.length > 1 ? `<button id="cv-prev"${at ? "" : " disabled"}>‹ Previous</button><button id="cv-next"${at < reel.length - 1 ? "" : " disabled"}>Next goal ›</button>` : ""}
        <a href="${esc(c.url)}" target="_blank" rel="noopener">Open on NHL.com ↗</a></div></div>`;
    root.querySelector(".cv-x").onclick = close;
    const prev = root.querySelector("#cv-prev"), next = root.querySelector("#cv-next");
    if (prev) { prev.onclick = () => go(-1); next.onclick = () => go(1); }
  }
  root.addEventListener("click", e => { if (e.target === root) close(); });
  history.pushState({ clip: true }, "");
  addEventListener("popstate", shut); addEventListener("hashchange", shut); addEventListener("keydown", key);
  draw();
  document.body.append(root);
  if (motionOn()) root.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 180, easing: "ease-out" });
  root.focus();
}
