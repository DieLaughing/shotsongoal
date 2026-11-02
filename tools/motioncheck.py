"""Motion check (docs/motion.md): a phone-sized headless Chromium opens the app (fixture data, tools/perf_server.py) and
checks the motion rules that can be measured.

  opens    every page opens fresh within OPEN_MS, stays responsive (no endless loop) and throws no page error
  still    an in-page switch tapped while scrolled down moves nothing: scroll position and the anchors (heading,
           the switch) stay within STILL_PX for STILL_MS
  pill     every visible switch's pill ends up under its picked option, within PILL_PX
  morph    tapping a card plays its shared-element transition (where the browser has View Transitions), lands on
           the page it opens and leaves no view-transition-name behind

    .venv/bin/python tools/motioncheck.py              # starts tools/perf_server.py on a spare port
    .venv/bin/python tools/motioncheck.py --url http://127.0.0.1:8788    # an app you're already running

Needs Playwright, like tools/perfcheck.py (PERF_CHROMIUM points at an installed Chromium). Exits 1 when a check fails.
In GitHub Actions the table also goes to the job summary. The part below the app's settings is the same in both apps."""
from __future__ import annotations

import argparse
import os
import shutil
import sys

from perfcheck import start_server

# ---- this app ----------------------------------------------------------------------------------------------------
PAGES = ["#/", "#/picks", "#/wire", "#/league", "#/leaders", "#/search", "#/settings", "#/new", "#/report", "#/app",
         "#/admin", "#/team/TBL", "#/player/8478402", "#/game/2026020084", "#/compare/BOS/TOR", "#/compare/BOS",
         "#/compare/p8478402/p8477956"]
# (page, what to tap, anchors that must not move). Taps are plain JS clicks: a real finger can only tap what's on
# screen, and Playwright's own click would scroll the target into view first (a jump the app didn't make).
STILL = [
    ("#/league", '.seg:not(.seg-top) button[data-mode="wildcard"]', ["#view .seg-top", ".seg:not(.seg-top)"]),
    ("#/league", '.seg:not(.seg-top) button[data-mode="league"]', ["#view .seg-top", ".seg:not(.seg-top)"]),
    ("#/league", '.seg-top a[href="#/leaders"]', ["#view .seg-top"]),
    ("#/wire", '#view .seg button[data-kind="news"]', ["#view h1", "#view .seg"]),
    ("#/team/TBL", '[data-ttab="players"]', ["#view .seg"]),
    ("#/player/8478402", '[data-ptab="career"]', ["#view .seg"]),
]
# Shared-element page changes (View Transitions): (page, card to tap, address it must land on, transition name).
MORPH = [("#/", "#view a.body", "#/game/", "matchup")]
SWITCHES, ON, PILL = ".seg, .league", ".on", ".seg-pill"
# The playful parts, driven by hand. Each returns (what, ok); anything that raises is a failure.
REPLAY_GAME = "#/game/2026020084"
SHOWN = "[...document.querySelectorAll('.rink [data-i]')].filter(e => e.style.display !== 'none').length"


def replay_check(page) -> tuple[str, bool]:
    """Dragging the puck hides shots that hadn't happened yet, leaves the page where it is, and the end brings them back."""
    page.wait_for_selector(".rp input", state="attached", timeout=3000)
    page.wait_for_timeout(400)   # its code arrives on idle
    move = "v => { const r = document.querySelector('.rp input'); r.value = v * r.max; r.dispatchEvent(new Event('input', { bubbles: true })); }"
    before, y = page.evaluate(SHOWN), page.evaluate("scrollY")
    page.evaluate(move, .4)
    mid, said = page.evaluate(SHOWN), page.inner_text(".rp-read")
    page.evaluate(move, 1)
    after = page.evaluate(SHOWN)
    ok = 0 < mid < before and after == before and page.evaluate("scrollY") == y and "Final" in page.inner_text(".rp-read")
    # A period button takes the map back from a replay, and leaving mid-replay must not draw the game over the next page.
    page.evaluate(move, .4)
    page.evaluate("document.querySelector('[data-shots]:not([data-shots=all])').click()")
    ok = ok and "Final" in page.inner_text(".rp-read")
    page.evaluate(move, .4)
    page.evaluate("document.querySelector('.rp-play').click(); location.hash = '#/league'")
    page.wait_for_timeout(700)
    ok = ok and not page.query_selector(".scorebug")
    return f"{before} → {mid} → {after} shots, {said.split(chr(10))[0]}", ok


def what_if_check(page) -> tuple[str, bool]:
    """Tapping a winner re-sorts the table with two more points; closing puts the real table back."""
    table = "[...document.querySelectorAll('tr[data-t]')].map(t => t.dataset.t + t.querySelector('b').textContent).join()"
    real = page.evaluate(table)
    page.evaluate("document.getElementById('whatif').click()")
    page.wait_for_selector(".wi-t", timeout=3000)
    page.evaluate("document.querySelector('.wi-t').click()")
    page.wait_for_selector(".wi-more", timeout=1000)
    changed = page.evaluate(table) != real
    page.evaluate("document.getElementById('wi-close').click()")
    return "re-sorted, then restored", changed and page.evaluate(table) == real and not page.query_selector(".wi")


def flick_check(page) -> tuple[str, bool]:
    """A game at a time: flicking saves the pick and moves on; closing lands back on the page, unlocked."""
    saved = []

    def future(route):   # the fixture's games are long past: put them all back before puck drop
        res = route.fetch()
        data = res.json()
        for g in data["games"]:
            g.update(state="pre", start="2099-01-01T00:00:00Z", mine=None)
        route.fulfill(response=res, json=data)

    def answer(route):   # the fixture's days are in the past, so the server would (rightly) refuse the pick
        route.fulfill(json={"ok": True})

    page.route("**/api/pickem?*", future)
    page.route("**/api/pickem", answer)
    page.reload()
    page.wait_for_selector("#flick:not([hidden])", timeout=3000)
    page.on("request", lambda r: saved.append(r.post_data) if r.method == "POST" and r.url.endswith("/api/pickem") else None)
    page.evaluate("document.getElementById('flick').click()")
    page.wait_for_selector(".fk-side", timeout=3000)
    page.evaluate("document.querySelector('.fk-side.h').click()")
    page.wait_for_timeout(400)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    return f"{len(saved)} pick saved", len(saved) == 1 and not page.query_selector(".flick") and page.evaluate("document.documentElement.style.overflow") == ""


def clip_check(page) -> tuple[str, bool]:
    """A goal's Watch button opens the league's player for that goal over the page; Escape takes it all away again."""
    page.route("**/players.brightcove.net/**", lambda route: route.fulfill(content_type="text/html", body="<!doctype html>player"))
    y = page.evaluate("scrollY")
    page.evaluate("document.querySelector('[data-clip]').click()")
    page.wait_for_selector(".clipview iframe", state="attached", timeout=3000)
    src = page.get_attribute(".clipview iframe", "src")
    page.keyboard.press("Escape")
    page.wait_for_timeout(100)
    return "opened and closed", "videoId=" in src and not page.query_selector(".clipview") and page.evaluate("scrollY") == y and page.evaluate("document.documentElement.style.overflow") == ""


def welcome_check(page) -> tuple[str, bool]:
    """Someone new gets one question a screen; several teams keep their order, and finishing saves it all and leaves the
    app usable."""
    saved = []

    def me(route):
        res = route.fetch()
        data = res.json()
        data["settings"].update(favorites=[], welcomed=False)
        route.fulfill(response=res, json=data)

    def settings(route):
        saved.append(route.request.post_data_json)
        route.fulfill(json=route.request.post_data_json)

    page.route("**/api/me", me)
    page.route("**/api/settings", settings)
    page.reload()
    page.wait_for_selector(".wl-t", timeout=3000)
    for team in ("LAK", "BOS"):
        page.evaluate("t => document.querySelector(`[data-t=${t}]`).click()", team)
    page.evaluate("document.querySelector('[data-main=BOS]').click()")   # the second tap becomes the main team
    for _ in range(3):
        page.evaluate("document.querySelector('.wl .go').click()")
    page.wait_for_timeout(200)
    got = saved[-1] if saved else {}
    return f"saved {got.get('favorites')}", got.get("favorites") == ["BOS", "LAK"] and got.get("welcomed") is True and not page.query_selector(".wl") and not page.evaluate("document.querySelector('main').inert")


def story_check(page) -> tuple[str, bool]:
    """A game's story starts at 0-0, the score and rink follow the swipe both ways, one moment fills the screen, and back closes it."""
    page.evaluate("document.getElementById('story').click()")
    page.wait_for_selector(".st", timeout=3000)
    page.wait_for_timeout(300)
    score = lambda: page.inner_text(".st-sc").replace("\n", "").replace(" ", "")
    go = "i => { const l = document.querySelector('.st-beats'); l.scrollTop = l.clientHeight * i; }"
    last = page.evaluate("document.querySelectorAll('.st-beat').length") - 1
    start = score()
    page.evaluate(go, last)
    page.wait_for_timeout(300)
    end, final = score(), page.inner_text(".st-when")
    page.evaluate(go, 0)
    page.wait_for_timeout(300)
    rewound = score()
    one = page.evaluate("""(() => { const l = document.querySelector('.st-beats').getBoundingClientRect();
      return [...document.querySelectorAll('.st-beat')].filter(b => { const r = b.getBoundingClientRect(); return r.top < l.bottom - 1 && r.bottom > l.top + 1; }).length; })()""")
    page.go_back()
    page.wait_for_timeout(200)
    gone = not page.query_selector(".st") and page.evaluate("document.documentElement.style.overflow") == "" and not page.evaluate("document.getElementById('view').inert")
    return f"{start} to {end}, {last + 1} moments", start == "0–0" and end != start and final.startswith("Final") and rewound == start and one == 1 and gone


def ribbon_check(page) -> tuple[str, bool]:
    """Dragging along the season changes what the read-out says and nothing else on the page."""
    page.wait_for_selector(".rb input", state="attached", timeout=3000)
    y, before = page.evaluate("scrollY"), page.inner_text("#rb-read")
    page.evaluate("() => { const r = document.querySelector('.rb input'); r.value = 0; r.dispatchEvent(new Event('input', { bubbles: true })); }")
    after = page.inner_text("#rb-read")
    return "read-out follows", after != before and "Game 1 " in after and page.evaluate("scrollY") == y and page.evaluate("document.querySelectorAll('.rb-bars .on').length") == 1


def compare_check(page) -> tuple[str, bool]:
    """Two teams give rows of numbers; the picker on a page with one team finds the other."""
    page.wait_for_selector(".cp-head", timeout=3000)
    rows = page.evaluate("document.querySelectorAll('.cp-rows .cmp').length")
    page.evaluate("location.hash = '#/compare/BOS'")
    page.wait_for_selector("#cp-q", timeout=3000)
    page.fill("#cp-q", "leafs")
    page.wait_for_selector("#cp-out a", timeout=3000)
    return f"{rows} rows", rows >= 4 and "compare/BOS/TOR" in page.get_attribute("#cp-out a", "href")


def dock_check(page) -> tuple[str, bool]:
    """Your team on now: the strip shows on other pages, a goal lights the lamp, and it's gone on that game's own page."""
    game = {"id": 2026020084, "league": "nhl", "date": "2026-10-11", "state": "live", "period": "2nd", "clock": "8:14", "intermission": False,
            "outcome": None, "start": None, "away": {"abbr": "BOS", "score": 1}, "home": {"abbr": "TOR", "score": 0}}
    page.route("**/api/live", lambda r: r.fulfill(json={"games": [game]}))
    settings = "s => fetch('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(s) }).then(r => r.json())"
    me = page.evaluate("fetch('/api/me').then(r => r.json()).then(m => m.settings)")
    page.evaluate(settings, {**me, "favorites": ["BOS"]})
    try:
        page.reload()
        page.wait_for_selector(".dock-item", timeout=4000)
        shown = page.inner_text(".dock-item .ms-sc").replace("\n", "")
        game["away"]["score"] = 2
        page.evaluate("import(performance.getEntriesByType('resource').find(e => e.name.includes('dock.js')).name).then(m => m.refresh())")
        page.wait_for_selector(".dock-item .lamp", state="attached", timeout=3000)
        page.evaluate(f"location.hash = '#/game/{game['id']}'")
        page.wait_for_timeout(600)
        gone = not page.query_selector(".dock-item")
    finally:
        page.evaluate(settings, me)
    return f"{shown}, then the lamp", shown.startswith("1") and gone


PLAY = [(REPLAY_GAME, "story", story_check), ("#/team/BOS", "ribbon", ribbon_check), ("#/compare/BOS/TOR", "compare", compare_check), ("#/wire", "dock", dock_check), (REPLAY_GAME, "replay", replay_check), (REPLAY_GAME, "clip", clip_check), ("#/", "welcome", welcome_check), ("#/league", "what if", what_if_check), ("#/picks", "flick", flick_check)]

# ---- the checks (the same in both apps) ---------------------------------------------------------------------------
OPEN_MS, SETTLE_MS, STILL_MS, STILL_PX, PILL_PX = 8000, 3200, 800, 1, 2
VIEWPORT = {"width": 390, "height": 844}

TRACK = """anchors => ({ y: scrollY, tops: anchors.map(s => { const e = document.querySelector(s);
  return e ? e.getBoundingClientRect().top : null; }) })"""
PILLS = """([sel, on, pill]) => [...document.querySelectorAll(sel)].filter(sw => sw.offsetParent).flatMap(sw => {
  const opt = sw.querySelector(`:scope > ${on}`); if (!opt) return [];
  const p = sw.querySelector(`:scope > ${pill}`);
  const name = sw.getAttribute("aria-label") || "." + [...sw.classList].filter(c => !["has-pill", "sliding"].includes(c)).join(".");
  if (!p) return [[name, "no pill"]];
  const a = p.getBoundingClientRect(), b = opt.getBoundingClientRect();
  return [[name, Math.max(Math.abs(a.left - b.left), Math.abs(a.width - b.width))]]; })"""
# Taps the first card on screen and lists the view-transition animations that run in the next 1.2 s.
MORPHS = """async tap => {
  const a = [...document.querySelectorAll(tap)].find(a => { const r = a.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; });
  if (!a) return null;
  const seen = new Set(), t0 = performance.now();
  a.click();
  while (performance.now() - t0 < 1200) {
    for (const an of document.getAnimations()) if (an.effect?.pseudoElement) seen.add(an.effect.pseudoElement);
    await new Promise(r => requestAnimationFrame(r));
  }
  return { vt: !!document.startViewTransition, seen: [...seen] };
}"""


def prepare(ctx, url: str) -> None:
    """Someone who's been here before: first-run setup would otherwise cover every page."""
    me = ctx.request.get(f"{url}/api/me").json()["settings"]
    ctx.request.put(f"{url}/api/settings", data={**me, "welcomed": True})


def check(url: str) -> list[tuple[str, str, str, bool]]:
    from playwright.sync_api import TimeoutError as PwTimeout, sync_playwright
    rows: list[tuple[str, str, str, bool]] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("PERF_CHROMIUM") or None)
        ctx = browser.new_context(viewport=VIEWPORT, is_mobile=True, has_touch=True, service_workers="block")
        prepare(ctx, url)

        def fresh(hash_: str):
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e).split("\n")[0]))
            page.goto(f"{url}/{hash_}", wait_until="commit")
            page.wait_for_timeout(SETTLE_MS)   # data, the phone's idiomorph (loaded 2.5 s in) and the pills
            return page, errors

        for hash_ in PAGES:
            page, errors = fresh(hash_)
            try:
                page.wait_for_function("() => document.getElementById('view')?.firstElementChild", timeout=OPEN_MS)
                page.wait_for_function("() => true", timeout=4000)   # a page stuck in an endless loop never answers
            except PwTimeout:
                rows.append(("opens", hash_, "frozen or empty", False))
                page.close()
                continue
            rows.append(("opens", hash_, "; ".join(errors) or "ok", not errors))
            page.wait_for_timeout(500)   # a pill that just slid finishes its 380 ms
            for name, off in page.evaluate(PILLS, [SWITCHES, ON, PILL]):
                ok = off != "no pill" and off <= PILL_PX
                rows.append(("pill", f"{hash_} {name}", off if isinstance(off, str) else f"{off:.1f} px off", ok))
            page.close()

        for hash_, tap, anchors in STILL:
            page, errors = fresh(hash_)
            target = page.query_selector(tap)
            if not target:
                rows.append(("still", f"{hash_} {tap}", "nothing to tap (fixture data changed?)", False))
                page.close()
                continue
            # Scroll down so the switch sits just under the top bar: as far down as someone can be and still tap it.
            page.evaluate("""tap => { const t = document.querySelector(tap).getBoundingClientRect().top;
              scrollTo(0, Math.max(0, Math.min(scrollY + t - 120, document.documentElement.scrollHeight - innerHeight))); }""", tap)
            page.wait_for_timeout(300)
            before = page.evaluate(TRACK, anchors)
            page.evaluate("tap => document.querySelector(tap).click()", tap)
            worst = 0.0
            for _ in range(STILL_MS // 40):
                page.wait_for_timeout(40)
                now = page.evaluate(TRACK, anchors)
                moves = [abs(now["y"] - before["y"])] + [abs(a - b) for a, b in zip(now["tops"], before["tops"]) if a is not None and b is not None]
                worst = max(worst, *moves)
            ok = worst <= STILL_PX and not errors
            rows.append(("still", f"{hash_} {tap}", "; ".join(errors) or f"moved {worst:.1f} px", ok))
            page.close()

        for hash_, tap, lands, name in MORPH:
            page, errors = fresh(hash_)
            got = page.evaluate(MORPHS, tap)
            page.wait_for_timeout(300)
            landed = page.evaluate("location.hash").startswith(lands)
            left = page.evaluate("() => document.querySelectorAll('[style*=view-transition-name]').length")
            played = not got or not got["vt"] or f"::view-transition-group({name})" in got["seen"]
            ok = bool(got) and played and landed and not left and not errors
            res = ("nothing to tap" if not got else "; ".join(errors) or ("no morph" if not played else "didn't land" if not landed
                   else f"{left} names left behind" if left else "morphed" if got["vt"] else "no View Transitions: plain change"))
            rows.append(("morph", f"{hash_} {tap}", res, ok))
            page.close()

        for hash_, name, drive in PLAY:
            page, errors = fresh(hash_)
            try:
                res, ok = drive(page)
            except Exception as e:
                res, ok = str(e).split("\n")[0], False
            rows.append((name, hash_, "; ".join(errors) or res, ok and not errors))
            page.close()
        browser.close()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", help="an app that's already running (default: start tools/perf_server.py)")
    args = ap.parse_args()
    proc = data = None
    url = args.url.rstrip("/") if args.url else None
    if not url:
        url, proc, data = start_server()
    try:
        rows = check(url)
    finally:
        if proc:
            proc.terminate()
            proc.wait(10)
            shutil.rmtree(data, ignore_errors=True)
    bad = [r for r in rows if not r[3]]
    lines = ["| check | where | result | |", "|---|---|---|---|"]
    lines += [f"| {k} | `{w}` | {res} | {'✅' if ok else '❌'} |" for k, w, res, ok in rows]
    report = "\n".join(lines) + f"\n\n**{f'{len(bad)} failed' if bad else 'all still'}** ({len(rows)} checks)\n"
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("## Motion\n\n" + report)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
