// First-run setup: a new friend answers one question per screen (teams, where they live, what they watch on) instead of
// meeting a long Settings page. Loaded only for people with no teams yet, or from Settings. Nothing is saved until the
// end or a skip, through the same saveSettings() as Settings.
const CSS = `
.wl { position: fixed; inset: 0; z-index: 30; display: flex; flex-direction: column; background: var(--bg); color: var(--text); outline: 0; }
.wl-head { flex: none; padding: calc(16px + env(safe-area-inset-top, 0px)) 16px 14px; color: #fff; transition: background-color 240ms ease;
  background: color-mix(in srgb, var(--c, #2a2f38) 70%, #0a0d12); }
.wl-pips { display: flex; gap: 5px; margin-bottom: 12px; }
.wl-pips i { flex: 1; height: 4px; border-radius: 2px; background: rgba(255, 255, 255, .25); }
.wl-pips i.on { background: #fff; }
.wl-head h1 { margin: 0 0 3px; font-size: 25px; line-height: 1.15; }
.wl-head p { margin: 0; font-size: 13.5px; color: rgba(255, 255, 255, .85); }
.wl-body { flex: 1; min-height: 0; overflow-y: auto; padding: 12px 16px; -webkit-overflow-scrolling: touch; }
.wl-inner, .wl-foot > div { width: 100%; max-width: 720px; margin: 0 auto; }
.wl-tabs { display: flex; gap: 6px; margin-bottom: 12px; }
.wl-tabs button { flex: 1; min-height: 38px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); color: var(--muted); font: inherit; font-weight: 700; cursor: pointer; }
.wl-tabs button.on { background: var(--text); color: var(--bg); }
.wl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(78px, 1fr)); gap: 8px; }
.wl-t { position: relative; display: grid; justify-items: center; gap: 5px; padding: 10px 2px 7px; border: 1.5px solid var(--border); border-radius: 12px; background: var(--surface); color: var(--text); font: inherit; font-size: 11px; font-weight: 650; line-height: 1.1; cursor: pointer; min-width: 0; }
.wl-t .mark { width: 46px; height: 36px; }
.wl-t.on { --ring: color-mix(in srgb, var(--c) 55%, var(--text)); border-color: var(--ring); box-shadow: inset 0 0 0 1.5px var(--ring); }
.wl-t em { position: absolute; top: 3px; right: 5px; font-style: normal; font-size: 12px; font-weight: 800; }
.wl-foot { flex: none; padding: 10px 16px calc(10px + env(safe-area-inset-bottom, 0px)); background: var(--surface); border-top: 1px solid var(--border); }
.wl-tray { display: flex; gap: 6px; overflow-x: auto; min-height: 38px; align-items: center; margin-bottom: 8px; scrollbar-width: none; }
.wl-tray:empty::before { content: "Nobody yet"; font-size: 12.5px; color: var(--muted); }
.wl-chip { flex: none; display: inline-flex; align-items: center; gap: 5px; min-height: 36px; padding: 0 9px 0 5px; border: 1px solid var(--border); border-radius: 18px; background: var(--bg); color: var(--text); font: inherit; font-size: 12.5px; font-weight: 650; cursor: pointer; }
.wl-chip.main { border-color: var(--text); }
.wl-acts { display: flex; align-items: center; gap: 8px; }
.wl-acts button { min-height: 44px; padding: 0 16px; border-radius: 12px; font: inherit; font-weight: 700; cursor: pointer; border: 1px solid var(--border); background: var(--bg); color: var(--text); }
.wl-acts .skip { border: 0; background: none; color: var(--muted); padding: 0 6px; font-weight: 600; }
.wl-acts .go { margin-left: auto; min-width: 120px; background: var(--text); color: var(--bg); border-color: var(--text); }
.wl-q { display: grid; gap: 6px; margin-bottom: 16px; font-weight: 700; font-size: 14px; }
.wl-q small { font-weight: 400; color: var(--muted); font-size: 12.5px; }
.wl-q select { width: 100%; min-height: 46px; padding: 0 10px; border-radius: 10px; border: 1px solid var(--border); background: var(--surface); color: var(--text); font: inherit; }
.wl-svc { display: grid; gap: 6px; }
.wl-svc label { display: flex; align-items: center; gap: 10px; min-height: 46px; padding: 0 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); font-weight: 600; cursor: pointer; }
.wl-svc input { width: 20px; height: 20px; accent-color: var(--c, var(--accent)); }`;

const LEAGUES = ["nhl", "pwhl", "ncaam", "ncaaw"];

export function open({ teams, leagueOf, mark, esc, name, colour, services, settings, save, done }) {
  if (!document.getElementById("wl-css")) document.head.append(Object.assign(document.createElement("style"), { id: "wl-css", textContent: CSS }));
  const root = Object.assign(document.createElement("div"), { className: "wl", tabIndex: -1 });
  root.setAttribute("role", "dialog"); root.setAttribute("aria-modal", "true"); root.setAttribute("aria-label", "Set up Shots on Goal");
  const behind = [...document.body.children], overflow = document.documentElement.style.overflow;
  document.documentElement.style.overflow = "hidden";
  behind.forEach(el => { el.inert = true; });

  let step = 0, league = "nhl", fav = [...settings.favorites || []], country = settings.country || "US", local = settings.local?.[0] || "", chose = !!settings.welcomed || !!settings.favorites?.length;
  const have = new Set(settings.services || []);

  function finish(patch) {
    root.remove();
    document.documentElement.style.overflow = overflow;
    behind.forEach(el => { el.inert = false; });
    save({ ...patch, welcomed: true }).then(done);   // the next page should be drawn from these answers
  }
  const answers = () => ({ favorites: fav, country, local: local ? [local] : [], services: [...have] });
  // Your first team in each league leads: the one the app dresses in when that league is on.
  const mains = () => new Set(LEAGUES.map(l => fav.find(a => leagueOf(a) === l)).filter(Boolean));

  const STEPS = [
    { title: "Who do you root for?", sub: "Tap as many as you like. Your first in each league is your main team, and the app wears its colours.",
      body: () => `<div class="wl-tabs">${[["nhl", "NHL"], ["pwhl", "PWHL"]].map(([k, l]) => `<button data-league-tab="${k}" class="${k === league ? "on" : ""}">${l}</button>`).join("")}</div>
        <div class="wl-grid">${teams.filter(t => leagueOf(t.abbr) === league).sort((x, y) => name(x.abbr).localeCompare(name(y.abbr))).map(t =>
          `<button class="wl-t" data-t="${esc(t.abbr)}" style="--c:${esc(colour(t.abbr))}" aria-pressed="false">${mark(t.abbr)}<span>${esc(name(t.abbr))}</span><em></em></button>`).join("")}</div>
        <p class="help">College teams? Add your schools in Settings afterwards.</p>` },
    { title: "Where do you watch from?", sub: "Blackouts depend on where you live, so this is how the app knows what you can actually see.",
      body: () => `<label class="wl-q">Country<select id="wl-country"><option value="US">United States</option><option value="CA"${country === "CA" ? " selected" : ""}>Canada</option></select></label>
        <label class="wl-q">Your home market<small>The NHL team whose games are blacked out where you live.</small><select id="wl-local"><option value="">None near me</option>${
          teams.filter(t => leagueOf(t.abbr) === "nhl").sort((x, y) => name(x.abbr).localeCompare(name(y.abbr))).map(t => `<option value="${esc(t.abbr)}"${t.abbr === local ? " selected" : ""}>${esc(name(t.abbr))}</option>`).join("")}</select></label>` },
    { title: "What do you watch on?", sub: "Tick what you have, and every game will say where to find it.",
      body: () => `<div class="wl-svc">${Object.entries(services).filter(([, v]) => (v.country || "US") === country && !v.college).map(([k, v]) =>
        `<label><input type="checkbox" value="${esc(k)}"${have.has(k) ? " checked" : ""}>${esc(v.label)}</label>`).join("")}</div>` },
  ];

  function dress() {
    const main = fav[0];
    root.style.setProperty("--c", main ? colour(main) : "#2a2f38");
    const lead = mains();
    root.querySelectorAll("[data-t]").forEach(b => {
      const on = fav.includes(b.dataset.t);
      b.classList.toggle("on", on); b.setAttribute("aria-pressed", on);
      b.querySelector("em").textContent = !on ? "" : lead.has(b.dataset.t) ? "★" : "✓";
    });
    const tray = root.querySelector(".wl-tray");
    if (tray) tray.innerHTML = fav.map(a => `<button class="wl-chip${lead.has(a) ? " main" : ""}" data-main="${esc(a)}" title="Make this your main team">${mark(a)}${lead.has(a) ? "★ " : ""}${esc(name(a))}</button>`).join("");
  }
  function draw() {
    const s = STEPS[step], last = step === STEPS.length - 1;
    root.innerHTML = `<div class="wl-head"><div class="wl-pips">${STEPS.map((_, i) => `<i class="${i <= step ? "on" : ""}"></i>`).join("")}</div><h1>${esc(s.title)}</h1><p>${esc(s.sub)}</p></div>
      <div class="wl-body"><div class="wl-inner">${s.body()}</div></div>
      <div class="wl-foot"><div>${step === 0 ? `<div class="wl-tray"></div>` : ""}<div class="wl-acts">${step ? `<button class="back">Back</button>` : `<button class="skip">Skip for now</button>`}<button class="go">${last ? "Done" : "Next"}</button></div></div></div>`;
    dress();
    root.querySelector(".go").onclick = () => { if (last) finish(answers()); else { step++; prepare(); draw(); } };
    const back = root.querySelector(".back"), skip = root.querySelector(".skip");
    if (back) back.onclick = () => { step--; draw(); };
    if (skip) skip.onclick = () => finish({});
    root.querySelector("#wl-country")?.addEventListener("change", e => { country = e.target.value; });
    root.querySelector("#wl-local")?.addEventListener("change", e => { local = e.target.value; chose = true; });
    root.querySelectorAll(".wl-svc input").forEach(i => i.addEventListener("change", () => { if (i.checked) have.add(i.value); else have.delete(i.value); }));
  }
  // Moving on from teams: the first NHL team is the likeliest home market, until they choose one themselves.
  function prepare() { if (step === 1 && !chose) local = fav.find(a => leagueOf(a) === "nhl") || local; }

  root.addEventListener("click", e => {
    const tab = e.target.closest("[data-league-tab]"), team = e.target.closest("[data-t]"), chip = e.target.closest("[data-main]");
    if (tab) { league = tab.dataset.leagueTab; draw(); }
    else if (team) { const a = team.dataset.t; fav = fav.includes(a) ? fav.filter(x => x !== a) : [...fav, a]; dress(); }
    else if (chip) { const a = chip.dataset.main; fav = [a, ...fav.filter(x => x !== a)]; dress(); }
  });
  draw();
  document.body.append(root);
  root.focus();
}
