"""Shots on Goal web server: access gate, JSON API and the web app."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import access, alerts, changes, ics, pwhl, teams, watch, wire
from .db import Store, parse_iso
from .feed import Feed
from .push import Pusher

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

DATA_DIR = Path(os.environ.get("SOG_DATA", Path(__file__).resolve().parent.parent / "data"))
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
ABBR = re.compile(r"^(PW-)?[A-Z]{2,3}$")  # NHL "BOS", PWHL "PW-BOS"
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REREQUEST_AFTER = timedelta(days=7)    # a denied or revoked person may ask again after this
RENOTIFY_AFTER = timedelta(hours=12)   # pressing Request twice doesn't ping the phone twice

store = Store(DATA_DIR / "sog.db")
feed = Feed(store)
pusher = Pusher(DATA_DIR, access.ADMIN)
feed.alerts = alerts.Alerts(store, pusher, access.BASE_URL)


NAME_CHECK_EVERY = 6 * 3600


async def check_pwhl_names() -> int:
    """Push to the owner (ntfy) once per PWHL team whose name no longer matches the app's team list, e.g. an
    expansion team getting its nickname. The fix is a one-line edit to sog/teams.py (and its colour)."""
    sent = 0
    for c in await feed.pwhl_name_changes():
        k = f"pwhl-name:{c['code']}:{c['feed']}"
        if store.was_sent(k):
            continue
        if c["ours"] is None:
            msg = f"The league lists a team the app doesn't know: {c['feed']} ({c['code']}). Add it to sog/teams.py."
        else:
            msg = (f"{c.get('full') or c['feed']}: the app still calls them \"{c['ours']}\". "
                   f"Update the PWHL team list (name and colours) in Shots on Goal.")
        if await access.notify(f"PWHL: {c['code']} is now the {c['feed']}" if c["ours"] else "PWHL: new team", msg, tags="ice_hockey"):
            store.mark_sent([k])
            sent += 1
    return sent


async def name_check_loop() -> None:
    while True:
        try:
            await check_pwhl_names()
        except Exception:
            logging.getLogger("sog.app").exception("PWHL name check failed")
        await asyncio.sleep(NAME_CHECK_EVERY)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [] if os.environ.get("SOG_NO_POLL") else [asyncio.create_task(feed.loop()), asyncio.create_task(name_check_loop())]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="Shots on Goal", lifespan=lifespan, docs_url=None, redoc_url=None)

# Paths anyone signed in may reach before approval. /act is reached without Cloudflare at all.
OPEN_API = {"/api/me", "/api/request"}


@app.middleware("http")
async def gate(request: Request, call_next):
    path = request.url.path
    email = access.email_from(request.headers)
    request.state.email = email
    user = store.user(email) if email else None
    if email and access.is_admin(email) and (not user or user["status"] != "approved"):
        store.set_status(email, "approved")  # the owner never waits on themself
        user = store.user(email)
    request.state.user = user
    if path.startswith("/api/") and path not in OPEN_API:
        if not email:
            return JSONResponse({"error": "not signed in"}, status_code=401)
        if not user or user["status"] != "approved":
            return JSONResponse({"error": "not approved"}, status_code=403)
        if path.startswith("/api/admin") and not access.is_admin(email):
            return JSONResponse({"error": "admin only"}, status_code=403)
    response = await call_next(request)
    if not path.startswith("/api/"):
        # Without this, Cloudflare caches .js/.css for hours and new versions don't show up.
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


# ---- people -------------------------------------------------------------------------
def _settings(request: Request) -> dict:
    return _user_settings(request.state.user, request.state.email)


def _user_settings(user: dict | None, email: str | None) -> dict:
    s = dict((user or {}).get("settings") or {})
    if access.is_admin(email) and not s:
        s = {"favorites": list(watch.DEFAULT_LOCAL), "services": ["espn_plus", "regional", "espn", "abc", "tnt"]}
    s.setdefault("favorites", [])
    s.setdefault("local", list(watch.DEFAULT_LOCAL))
    s["notify"] = alerts.prefs(s)
    return s


@app.get("/api/me")
def me(request: Request):
    email, user = request.state.email, request.state.user
    return {"email": email, "status": (user or {}).get("status", "none") if email else "signed-out",
            "admin": access.is_admin(email), "settings": _settings(request) if user else None,
            "services": watch.services(), "teams": teams.as_list()}


@app.post("/api/request")
async def request_access(request: Request):
    email, user = request.state.email, request.state.user
    if not email:
        raise HTTPException(401)
    now = datetime.now(timezone.utc)
    status = (user or {}).get("status")
    if status == "approved":
        return {"status": "approved"}
    if status in ("denied", "revoked") and user.get("decided") and now - parse_iso(user["decided"]) < REREQUEST_AFTER:
        return {"status": status}
    if status == "pending" and user.get("requested") and now - parse_iso(user["requested"]) < RENOTIFY_AFTER:
        return {"status": "pending"}
    nonce = secrets.token_urlsafe(9)
    store.set_status(email, "pending", nonce)
    await access.notify_request(DATA_DIR, email, nonce)
    return {"status": "pending"}


@app.put("/api/settings")
async def save_settings(request: Request):
    body = await request.json()
    clean = {
        "favorites": [t for t in body.get("favorites") or [] if t in teams.ALL][:44],
        "local": [t for t in body.get("local") or [] if t in teams.TEAMS][:8],  # blackouts are an NHL thing
        "services": [s for s in body.get("services") or [] if s in watch.services()],
        "notify": {k: bool((body.get("notify") or {}).get(k, True)) for k in alerts.KINDS},
        "seen_changes": str(body.get("seen_changes") or "")[:120],  # newest What's new entry this person has seen
    }
    store.save_settings(request.state.email, clean)
    return clean


# ---- notifications -------------------------------------------------------------------------
@app.get("/api/push")
def push_info(request: Request):
    return {"key": pusher.public_key, "devices": len(store.pushes(request.state.email))}


@app.post("/api/push/subscribe")
async def push_subscribe(request: Request):
    body = await request.json()
    sub = body.get("subscription") or {}
    if not str(sub.get("endpoint", "")).startswith("https://") or not (sub.get("keys") or {}).get("p256dh"):
        raise HTTPException(400)
    store.add_push(request.state.email, sub, request.headers.get("user-agent"))
    return {"ok": True}


@app.post("/api/push/unsubscribe")
async def push_unsubscribe(request: Request):
    body = await request.json()
    store.remove_push(str(body.get("endpoint") or ""), request.state.email)
    return {"ok": True}


@app.post("/api/push/test")
async def push_test(request: Request):
    subs = store.pushes(request.state.email)
    n = await feed.alerts.send(subs, {"title": "Shots on Goal", "body": "Notifications work on this device.",
                                      "url": f"{access.BASE_URL}/#/settings", "tag": "test"})
    return {"sent": n, "devices": len(subs)}


@app.post("/api/report")
async def report(request: Request):
    """'Wrong channel?' on a game page: saved for /admin and pushed to the owner."""
    body = await request.json()
    try:
        gid = int(body.get("game_id"))
    except (TypeError, ValueError):
        raise HTTPException(400)
    detail = await _upstream(feed.game(gid))
    g = dict(detail["game"])
    w = watch.watch_for(g, _settings(request)["local"], _settings(request).get("services"))
    game = f"{g['away']['abbr']} at {g['home']['abbr']}, {g['date']}"
    shown = f"{w.get('app') or 'nothing'} ({w.get('why')})"
    note = str(body.get("note") or "").strip()[:300]
    store.add_report(request.state.email, gid, game, shown, note)
    await access.notify("Shots on Goal: wrong channel?", f"{game}: showed {shown}. {request.state.email}: {note or '(no note)'}",
                        tags="tv", click=f"{access.BASE_URL}/#/admin")
    return {"ok": True}


@app.post("/act/{token}")
async def act(token: str):
    """Approve/Deny buttons in the ntfy push. Single-use: the nonce dies with the first decision.
    ntfy shows nothing when a button works, so a short confirmation push follows."""
    link = access.verify(DATA_DIR, token)
    if not link or link["action"] not in ("approve", "deny"):
        return PlainTextResponse("This link is invalid or has expired.", status_code=410)
    email, status = link["email"], "approved" if link["action"] == "approve" else "denied"
    user = store.user(email)
    if user and user["status"] == status and not user["nonce"]:
        return PlainTextResponse(f"{email} was already {status}.")  # a second tap on the same button
    if not user or user["status"] != "pending" or user["nonce"] != link["nonce"]:
        return PlainTextResponse("Already handled.", status_code=409)
    store.set_status(email, status)
    await access.notify(f"{email} {status}",
                        "They're in. Their next page load shows the site." if status == "approved"
                        else "They'll see a no-access page.", tags="white_check_mark" if status == "approved" else "x")
    return PlainTextResponse(f"{email}: {status}.")


@app.get("/invite/{code}")
async def invite(code: str, request: Request):
    email = request.state.email
    if not email:
        raise HTTPException(401)
    user = request.state.user
    if user and user["status"] == "approved":
        return RedirectResponse("/")
    if not store.use_invite(code, email):
        return HTMLResponse("<p>This invite link has already been used or doesn't exist. "
                            "<a href='/'>Request access instead</a>.</p>", status_code=410)
    store.set_status(email, "approved")
    await access.notify("Shots on Goal: invite used", f"{email} joined with an invite link.", tags="tada")
    return RedirectResponse("/")


# ---- admin ----------------------------------------------------------------------------
@app.get("/api/admin")
def admin_overview(request: Request):
    base = access.BASE_URL
    return {"users": [{k: u[k] for k in ("email", "status", "requested", "decided")} for u in store.users()],
            "invites": [{**i, "link": f"{base}/invite/{i['code']}"} for i in store.invites()],
            "sources": store.runs(), "insiders": store.insiders({"nhl": wire.DEFAULT_INSIDERS, "pwhl": wire.PWHL_INSIDERS}), "reports": store.reports()}


@app.post("/api/admin/reports/{rid}/resolve")
def admin_resolve_report(rid: int):
    store.resolve_report(rid)
    return {"ok": True}


HANDLE = re.compile(r"^[a-z0-9][a-z0-9.-]{2,252}$")


@app.post("/api/admin/insiders")
async def admin_add_insider(request: Request):
    body = await request.json()
    handle = (body.get("handle") or "").strip().lower().lstrip("@")
    handle = re.sub(r"^https?://bsky\.app/profile/", "", handle).split("/")[0]
    if "." not in handle:
        handle += ".bsky.social"  # "russohockey" -> russohockey.bsky.social
    if not HANDLE.match(handle):
        raise HTTPException(400, "That doesn't look like a Bluesky handle.")
    profile = await wire.check_handle(handle)
    if not profile:
        raise HTTPException(404, f"Bluesky doesn't know {handle}.")
    store.add_insider(profile["handle"], (body.get("label") or "").strip()[:60] or profile["name"],
                      "pwhl" if body.get("league") == "pwhl" else "nhl")
    return profile


@app.delete("/api/admin/insiders/{handle}")
def admin_remove_insider(handle: str):
    store.remove_insider(handle)
    return {"ok": True}


@app.post("/api/admin/users")
async def admin_set_user(request: Request):
    body = await request.json()
    email, status = (body.get("email") or "").strip().lower(), body.get("status")
    if not email or status not in ("approved", "denied", "revoked"):
        raise HTTPException(400)
    if access.is_admin(email):
        raise HTTPException(400, "can't change the owner")
    store.set_status(email, status)
    return {"ok": True}


@app.post("/api/admin/invites")
async def admin_new_invite(request: Request):
    body = await request.json()
    code = secrets.token_urlsafe(12)
    store.add_invite(code, (body.get("note") or "")[:80] or None)
    return {"code": code, "link": f"{access.BASE_URL}/invite/{code}"}


@app.delete("/api/admin/invites/{code}")
def admin_delete_invite(code: str):
    store.delete_invite(code)
    return {"ok": True}


# ---- hockey ----------------------------------------------------------------------------
PWHL_WATCH = {"network": None, "app": "PWHL listings", "why": "Streams and TV vary by game",
              "service": None, "have": None, "url": pwhl.WHERE_TO_WATCH,
              "links": [{"name": "Where to watch (PWHL)", "url": pwhl.WHERE_TO_WATCH}]}


def _with_watch(games: list[dict], s: dict) -> list[dict]:
    have = s.get("services") if "services" in s else None
    for g in games:
        if g.get("league") == "pwhl":
            g["watch"] = dict(PWHL_WATCH)  # the feed lists no broadcasters; the league's page does
            continue
        g["watch"] = watch.watch_for(g, s["local"], have)
        if have is None:
            g["watch"]["have"] = None  # services not set yet: don't claim they're missing
    return games


async def _upstream(coro):
    try:
        return await coro
    except Exception as exc:
        raise HTTPException(502, f"NHL data unavailable right now ({type(exc).__name__})")


@app.get("/api/games")
async def games(request: Request, date: str | None = None, league: str = "nhl"):
    if date and not DATE.match(date):
        raise HTTPException(400)
    if league == "pwhl":
        day = await _upstream(feed.pwhl_day(date))
        return {**day, "games": _with_watch([dict(g) for g in day["games"]], _settings(request))}
    # No date = the NHL's own "today" (Eastern), kept fresh by the poller.
    target = date or feed.today
    day = await _upstream(feed.day(target) if target else feed.poll_today())
    return {**day, "games": _with_watch([dict(g) for g in day["games"]], _settings(request))}


@app.get("/api/game/{game_id}")
async def game(game_id: int, request: Request):
    detail = await _upstream(feed.game(game_id))
    detail = {**detail, "game": dict(detail["game"])}
    _with_watch([detail["game"]], _settings(request))
    return detail


@app.get("/api/pwhl/game/{game_id}")
async def pwhl_game(game_id: int, request: Request):
    detail = await _upstream(feed.pwhl_game(game_id))
    detail = {**detail, "game": dict(detail["game"])}
    _with_watch([detail["game"]], _settings(request))
    return detail


@app.get("/api/standings")
async def standings(league: str = "nhl"):
    return await _upstream(feed.pwhl_standings() if league == "pwhl" else feed.standings())


@app.get("/api/team/{abbr}")
async def team(abbr: str, request: Request):
    abbr = abbr.upper()
    if not ABBR.match(abbr) or abbr not in teams.ALL:
        raise HTTPException(404)
    data, items = await asyncio.gather(feed.pwhl_team(abbr) if abbr.startswith("PW-") else feed.team(abbr), feed.wire())
    sched = [dict(g) for g in data["schedule"] if g.get("type") in (2, 3)] or [dict(g) for g in data["schedule"]]
    return {**data, "schedule": _with_watch(sched, _settings(request)),
            "wire": [i for i in items if abbr in i["teams"]][:20]}


WIRE_KINDS = {"move", "news", "insider"}


@app.get("/api/wire")
async def wire_feed(request: Request, kind: str | None = None, team: str | None = None, mine: bool = False,
                    league: str | None = None):
    items = await feed.wire()
    if league in ("nhl", "pwhl"):
        items = [i for i in items if i.get("league", "nhl") == league]
    if kind in WIRE_KINDS:
        items = [i for i in items if i["kind"] == kind]
    if team:
        items = [i for i in items if team.upper() in i["teams"]]
    if mine:
        fav = set(_settings(request)["favorites"])
        items = [i for i in items if fav & set(i["teams"])]
    return items[:150]


# ---- calendar feeds ---------------------------------------------------------------------
@app.get("/api/calendar")
def calendar_link(request: Request):
    token = store.cal_token(request.state.email, lambda: secrets.token_urlsafe(24))
    return {"token": token, "base": access.BASE_URL}


@app.get("/cal/{token}/{codes}.ics")
async def calendar(token: str, codes: str):
    """Calendar apps can't sign in to Cloudflare, so /cal skips Access and the per-person token guards it.
    Revoking someone kills their feed too."""
    user = store.user_by_cal_token(token)
    if not user or user["status"] != "approved":
        raise HTTPException(404)
    abbrs = [c for c in codes.upper().split("+") if c in teams.ALL][:8]
    if not abbrs:
        raise HTTPException(404)
    s = _user_settings(user, user["email"])
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    games, seen = [], set()
    for abbr in abbrs:
        data = await (feed.pwhl_team(abbr) if abbr.startswith("PW-") else feed.team(abbr))
        for g in data["schedule"]:
            if g["id"] in seen or g.get("type") not in (2, 3) or (g.get("start") or "") < cutoff:
                continue
            seen.add(g["id"])
            games.append(dict(g))
    games.sort(key=lambda g: g.get("start") or "")
    _with_watch(games, s)
    title = "Hockey: " + ", ".join(teams.ALL[a][1] for a in abbrs)
    return Response(ics.build(games, access.BASE_URL, title), media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "max-age=900"})


@app.get("/api/changes")
def whats_new():
    return changes.load()


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ---- web app ----------------------------------------------------------------------------
def _asset_version() -> str:
    """Changes whenever any web file changes, so browsers and Cloudflare fetch fresh copies."""
    return hashlib.sha1("".join(f"{p.name}{p.stat().st_mtime_ns}" for p in sorted(WEB_DIR.rglob("*"))
                                if p.is_file()).encode()).hexdigest()[:10]


@app.get("/")
def index():
    v = _asset_version()
    page = (WEB_DIR / "index.html").read_text()
    page = page.replace('src="app.js"', f'src="app.js?v={v}"').replace('href="style.css"', f'href="style.css?v={v}"')
    return HTMLResponse(page, headers={"Cache-Control": "no-cache"})


app.mount("/", StaticFiles(directory=WEB_DIR), name="web")
