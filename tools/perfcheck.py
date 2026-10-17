"""Speed budget check (docs/operating.md): a phone-sized headless Chromium with 200 ms added to every request (the
"slow relay") opens the app, visits every tab and a game and team page, then comes back to each one. Every API call the
pages made is then timed directly against the server.

  first visit    content on screen after opening the app with nothing cached          < FIRST_MS
  revisit        content on screen after going back to a page already seen            < REVISIT_MS
  api p95        95th percentile of RUNS direct requests to each API path the pages use < API_P95_MS

    .venv/bin/python tools/perfcheck.py              # starts tools/perf_server.py (fixture data) on a spare port
    .venv/bin/python tools/perfcheck.py --url http://127.0.0.1:8788    # an app you're already running

Needs Playwright (`.venv/bin/pip install playwright`, then `.venv/bin/playwright install chromium`, or point
PERF_CHROMIUM at an installed Chromium). Exits 1 when anything is over budget. In GitHub Actions the table also goes to
the job summary."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIRST_MS, REVISIT_MS, API_P95_MS = 1500, 300, 200
LATENCY_MS = 200          # added to every request: the slow relay
DOWN_KBPS = 1600          # a slow phone connection (~"slow 4G")
RUNS = 20
TABS = ["#/picks", "#/wire", "#/league", "#/settings", "#/"]
DETAIL = ['a[href^="#/game/"]', 'a[href^="#/team/"]']    # found on the pages: the first game and team link

# New content in #view: a first element that wasn't there before and isn't the "Loading…" placeholder.
READY = """old => { const f = document.getElementById("view").firstElementChild;
  return !!f && f !== old && !(f.classList.contains("empty") && /^Loading/.test(f.textContent)); }"""
GO = """async ([hash, wait]) => {
  const ready = %s, old = document.getElementById("view").firstElementChild, t0 = performance.now();
  location.hash = hash;
  return await new Promise(done => {
    const check = () => ready(old) ? done(performance.now() - t0)
      : performance.now() - t0 > wait ? done(null) : requestAnimationFrame(check);
    requestAnimationFrame(check);
  });
}""" % READY
FIRST = """() => new Promise(done => {
  const check = () => document.getElementById("view") && (%s)(null) ? done(performance.now()) : requestAnimationFrame(check);
  check();
})""" % READY


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server() -> tuple[str, subprocess.Popen, str]:
    port, data = free_port(), tempfile.mkdtemp(prefix="sog-perf-")
    proc = subprocess.Popen([sys.executable, str(ROOT / "tools" / "perf_server.py"), "--port", str(port), "--data", data])
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{url}/healthz", timeout=1)
            return url, proc, data
        except OSError:
            time.sleep(0.1)
    proc.kill()
    sys.exit("perf server didn't start")


def browse(url: str) -> tuple[float, dict[str, float | None], set[str]]:
    from playwright.sync_api import sync_playwright
    apis: set[str] = set()
    with sync_playwright() as pw:
        exe = os.environ.get("PERF_CHROMIUM") or None
        browser = pw.chromium.launch(executable_path=exe)
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                                  service_workers="block")   # a first visit has no service worker yet
        page = ctx.new_page()
        page.on("request", lambda r: apis.add(r.url[len(url):]) if r.method == "GET" and r.url.startswith(f"{url}/api/") else None)
        cdp = ctx.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": LATENCY_MS,
                                                      "downloadThroughput": DOWN_KBPS * 125, "uploadThroughput": DOWN_KBPS * 125})
        page.goto(url + "/", wait_until="commit")
        first = page.evaluate(FIRST)
        page.wait_for_timeout(4000)                  # prefetch() runs 2.5 s after start
        pages = list(TABS)
        for sel in DETAIL:                           # a game page and a team page, from links the app shows
            for hop in ["#/", "#/league"]:
                page.evaluate(GO, [hop, 10000])
                href = page.eval_on_selector(sel, "a => a.getAttribute('href')") if page.query_selector(sel) else None
                if href:
                    pages.append(href)
                    break
        for hash in pages:                           # see each page once, then come back to it
            page.evaluate(GO, [hash, 10000])
            page.evaluate(GO, ["#/new", 10000])
        revisit = {}
        for hash in pages:
            page.evaluate(GO, ["#/new" if hash != "#/new" else "#/", 10000])
            revisit[hash] = page.evaluate(GO, [hash, 5000])
        browser.close()
    return first, revisit, apis


def time_apis(url: str, paths: set[str]) -> dict[str, float]:
    out = {}
    for path in sorted(paths):
        took = []
        for _ in range(RUNS):
            t0 = time.perf_counter()
            with urllib.request.urlopen(url + path, timeout=10) as r:
                r.read()
            took.append((time.perf_counter() - t0) * 1000)
        took.sort()
        out[path] = took[max(0, int(len(took) * 0.95) - 1)]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", help="an app that's already running (default: start tools/perf_server.py)")
    ap.add_argument("--json", help="also write the results here")
    args = ap.parse_args()
    proc = data = None
    url = args.url.rstrip("/") if args.url else None
    if not url:
        url, proc, data = start_server()
    try:
        first, revisit, apis = browse(url)
        api = time_apis(url, apis)
    finally:
        if proc:
            proc.terminate()
            proc.wait(10)
            shutil.rmtree(data, ignore_errors=True)

    rows = [("first visit", "/", first, FIRST_MS)]
    rows += [("revisit", h, ms, REVISIT_MS) for h, ms in revisit.items()]
    rows += [("api p95", p, ms, API_P95_MS) for p, ms in api.items()]
    bad = [r for r in rows if r[2] is None or r[2] > r[3]]
    lines = ["| check | page | ms | budget | |", "|---|---|---:|---:|---|"]
    lines += [f"| {k} | `{p}` | {'timeout' if ms is None else round(ms)} | {b} | {'❌' if ms is None or ms > b else '✅'} |"
              for k, p, ms, b in rows]
    verdict = f"{len(bad)} over budget" if bad else "all within budget"
    report = "\n".join(lines) + f"\n\n**{verdict}** (slow relay {LATENCY_MS} ms per request, {DOWN_KBPS} kbps)\n"
    print(report)
    if args.json:
        Path(args.json).write_text(json.dumps({"ok": not bad, "rows": rows}, indent=1))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("## Speed budget\n\n" + report)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
