"""Shots on Goal web server: access gate, JSON API and the web app."""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from . import access, bugs, alerts, changes, home, ics, picks, pwhl, social, spoilers, teams, watch, wire
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
SLOW = 0.5                             # seconds: API requests slower than this are logged
log = logging.getLogger("sog.app")

store = Store(DATA_DIR / "sog.db")
bugs.init(store.conn)
picks.init(store.conn)
social.init(store.conn)
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
                   f"Ask Claude to update the PWHL team list (name and colours) in Shots on Goal.")
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


app.add_middleware(GZipMiddleware, minimum_size=1500)  # JSON and app.js shrink ~5x on the way out


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
    started = time.perf_counter()
    response = await call_next(request)
    took = time.perf_counter() - started
    if path.startswith("/api/") and took > SLOW:
        log.warning("slow request: %s %s %.0f ms", request.method, path, took * 1000)
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
    s["spoilers"] = spoilers.clean(s.get("spoilers"), teams.ALL)
    return s



# ---- bug reports (filed as GitHub issues, anonymously; see bugs.py) ------------------------------------
@app.post("/api/bug")
async def bug_report(request: Request):
    body = await request.json()
    kind = body.get("kind") if body.get("kind") in bugs.KINDS else "bug"
    text = str(body.get("text") or "").strip()[:4000]
    if len(text) < 10:
        raise HTTPException(400, "Tell us a bit more (at least a sentence).")
    page = str(body.get("page") or "")[:200]
    device = str(body.get("device") or "")[:120]
    version = (changes.load() or [{}])[0].get("date", "")
    email = request.state.email
    if not bugs.configured():
        return {"link": bugs.new_issue_link(kind, text, page, device, version)}
    if not access.is_admin(email) and bugs.sent_today(email) >= bugs.PER_DAY:
        raise HTTPException(429, "That's a lot of reports for one day. Thanks! Try again tomorrow.")
    try:
        out = await bugs.file(email, kind, text, page, device, version)
    except Exception as exc:
        # An expired or revoked token shouldn't lose the report: hand over GitHub's own form and tell the owner.
        logging.getLogger("sog.app").warning("filing a bug report failed: %r", exc)
        await access.notify("Bug report couldn't be filed", f"GitHub said: {exc!r}"[:300] + " (check the GitHub token)", tags="warning")
        return {"link": bugs.new_issue_link(kind, text, page, device, version)}
    await access.notify(f"Shots on Goal: new {bugs.KINDS[kind][0].lower()} #{out['issue']}", out["title"],
                        tags="bug", click=out["url"])
    return out


@app.get("/api/bugs")
async def my_bug_reports(request: Request):
    return {"reports": await bugs.mine(request.state.email), "repo": bugs.REPO, "filing": bugs.configured()}

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


def clean_name(raw) -> str:
    text = "".join(c for c in str(raw or "") if c.isprintable())
    return " ".join(text.split())[:24]


def people() -> dict[str, dict]:
    """Everyone approved: email -> {name friends see, favorites}. Emails never leave the server."""
    found = social.friends(store.users(), access.ADMIN)
    if access.ADMIN and access.ADMIN not in found:
        found[access.ADMIN] = {"name": social.display_name(access.ADMIN, None), "favorites": []}
    return found


def friend_names() -> dict[str, str]:
    return {e: p["name"] for e, p in people().items()}


@app.put("/api/settings")
async def save_settings(request: Request):
    body = await request.json()
    clean = {
        "favorites": [t for t in body.get("favorites") or [] if t in teams.ALL][:44],
        "local": [t for t in body.get("local") or [] if t in teams.TEAMS][:8],  # blackouts are an NHL thing
        "services": [s for s in body.get("services") or [] if s in watch.services()],
        "notify": alerts.prefs(body),
        "seen_changes": str(body.get("seen_changes") or "")[:120],  # newest What's new entry this person has seen
        "spoilers": spoilers.clean(body.get("spoilers"), teams.ALL),
        "nickname": clean_name(body.get("nickname")),
        "hand": "left" if body.get("hand") == "left" else "right",  # which side game buttons sit on touch screens
        "animations": body.get("animations") is not False,  # page transitions (Settings > Display); on unless turned off  # what friends see in Pick'em; empty = the email's first part
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
    inv = store.invite(code)
    # A group link mustn't undo a decision about this person; a link made for them alone still can.
    shut_out = user and user["status"] in ("denied", "revoked") and inv and inv["max_uses"] > 1
    if shut_out or not store.use_invite(code, email):
        return HTMLResponse("<p>This invite link is used up or doesn't exist. "
                            "<a href='/'>Request access instead</a>.</p>", status_code=410)
    store.set_status(email, "approved")
    joined = f" ({len(inv['uses']) + 1} of {inv['max_uses']})" if inv["max_uses"] > 1 else ""
    note = f" \"{inv['note']}\"" if inv["note"] else ""
    await access.notify("Shots on Goal: invite used", f"{email} joined with the invite link{note}{joined}.", tags="tada")
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
    try:
        uses = min(max(int(body.get("uses") or 1), 1), 50)
    except (TypeError, ValueError):
        raise HTTPException(400, "uses must be a number")
    store.add_invite(code, (body.get("note") or "")[:80] or None, uses)
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


_cleaned = {"at": datetime.min.replace(tzinfo=timezone.utc)}


def _with_watchers(games: list[dict], request: Request) -> list[dict]:
    now = datetime.now(timezone.utc)
    if now - _cleaned["at"] > timedelta(hours=1):
        social.cleanup(feed.opening_day())
        _cleaned["at"] = now
    found = social.watchers(games, request.state.email, people())
    for g in games:
        g["watching"] = found.get(f"{social.league(g)}:{g['id']}", [])
    return games


@app.get("/api/games")
async def games(request: Request, date: str | None = None, league: str = "nhl"):
    if date and not DATE.match(date):
        raise HTTPException(400)
    if league == "pwhl":
        day = await _upstream(feed.pwhl_day(date))
        return {**day, "games": _with_watchers(_with_watch([dict(g) for g in day["games"]], _settings(request)), request)}
    # No date = today in Eastern time (last night's games until 6 am); see feed.slate_date.
    target = date or feed.opening_day()
    day = await _upstream(feed.today_page() if target == feed.today else feed.day(target))
    return {**day, "games": _with_watchers(_with_watch([dict(g) for g in day["games"]], _settings(request)), request)}


LIVE_FIELDS = ("state", "raw_state", "period", "clock", "running", "intermission", "outcome", "situation")


def _freshen(g: dict) -> dict:
    """A game page can be a minute or two old; the scoreboard is refreshed every 10 seconds while games are on.
    Take the score, clock and state from whichever saved scoreboard has this game."""
    for key in ("score:now", f"score:{g.get('date')}"):
        hit = store.get(key)
        live = next((x for x in (hit["data"]["games"] if hit else []) if x["id"] == g["id"]), None)
        if live and live["state"] in ("live", "final"):
            g.update({k: live.get(k) for k in LIVE_FIELDS if k in live})
            for side in ("away", "home"):
                g[side] = {**g[side], "score": live[side].get("score"), "sog": live[side].get("sog", g[side].get("sog"))}
            return g
    return g


@app.get("/api/game/{game_id}")
async def game(game_id: int, request: Request):
    detail = await _upstream(feed.game(game_id))
    detail = {**detail, "game": _freshen(dict(detail["game"]))}
    _with_watch([detail["game"]], _settings(request))
    return {**detail, "social": social.for_game(request.state.email, detail["game"], people())}


@app.get("/api/pwhl/game/{game_id}")
async def pwhl_game(game_id: int, request: Request):
    detail = await _upstream(feed.pwhl_game(game_id))
    detail = {**detail, "game": dict(detail["game"], league="pwhl")}
    _with_watch([detail["game"]], _settings(request))
    return {**detail, "social": social.for_game(request.state.email, detail["game"], people())}


# ---- finished responses ------------------------------------------------------------------------
# The biggest shared answers (the Wire, standings) are turned into JSON and compressed once per change of the data,
# then sent as they are. Keyed by what they depend on; a handful of entries, so no eviction policy beyond a cap.
_ready: dict[tuple, tuple] = {}


def _finished(request: Request, key: tuple, version, build) -> Response:
    hit = _ready.get(key)
    if not hit or hit[0] != version:
        raw = json.dumps(build(), separators=(",", ":"), ensure_ascii=False).encode()
        hit = (version, raw, gzip.compress(raw, 6) if len(raw) > 1500 else None)
        if len(_ready) > 200:
            _ready.clear()
        _ready[key] = hit
    if hit[2] and "gzip" in request.headers.get("accept-encoding", ""):
        return Response(hit[2], media_type="application/json", headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
    return Response(hit[1], media_type="application/json")


@app.get("/api/standings")
async def standings(request: Request, league: str = "nhl"):
    key = "pwhl:standings" if league == "pwhl" else "standings"
    rows = await _upstream(feed.pwhl_standings() if league == "pwhl" else feed.standings())
    meta = store.meta(key)
    return _finished(request, ("standings", key), meta[:2] if meta else None, lambda: rows)


@app.get("/api/team/{abbr}")
async def team(abbr: str, request: Request):
    abbr = abbr.upper()
    if not ABBR.match(abbr) or abbr not in teams.ALL:
        raise HTTPException(404)
    data, items = await asyncio.gather(feed.pwhl_team(abbr) if abbr.startswith("PW-") else feed.team(abbr), feed.wire())
    sched = [dict(g) for g in data["schedule"] if g.get("type") in (2, 3)] or [dict(g) for g in data["schedule"]]
    # The page shows recent results and what's coming up: send those, not the whole season (or two, for the PWHL).
    done = [g for g in sched if g.get("state") == "final"]
    sched = done[-10:] + [g for g in sched if g.get("state") != "final"][:10]
    career = feed.careers(abbr) if not abbr.startswith("PW-") else None
    return {**data, "schedule": _with_watch(sched, _settings(request)),
            "wire": [i for i in items if abbr in i["teams"]][:20],
            "milestones": home.near_milestones(career["players"]) if career else []}


@app.get("/api/myteams")
async def my_teams(request: Request):
    """The "your team" cards on Tonight: one summary per favourite, from the cached schedules and standings."""
    s = _settings(request)
    picks = [a for a in s["favorites"] if a in teams.ALL]
    if not picks:
        return {"teams": []}
    today = feed.opening_day()

    async def one(abbr: str, rows: list[dict]) -> dict | None:
        lg = teams.league_of(abbr)
        try:
            schedule = await feed.team_schedule(abbr)  # schedule only: the card needs no roster or stats
        except Exception:
            return None
        sched = [dict(g) for g in schedule if g.get("type") in (2, 3)] or [dict(g) for g in schedule]
        card = home.team_summary(abbr, sched, rows, today, lg)
        career = feed.careers(abbr) if lg == "nhl" else None  # saved copy only: never waits on 25 player pages
        card["milestones"] = home.near_milestones(career["players"])[:1] if career else []
        if card["next"]:
            _with_watch([card["next"]], s)
        return card

    leagues = {teams.league_of(a) for a in picks}
    rows = dict(zip(leagues, await asyncio.gather(
        *[(feed.pwhl_standings() if lg == "pwhl" else feed.standings()) for lg in leagues], return_exceptions=True)))
    rows = {lg: [] if isinstance(r, Exception) else r for lg, r in rows.items()}
    cards = await asyncio.gather(*[one(a, rows[teams.league_of(a)]) for a in picks])
    return {"date": today, "teams": [c for c in cards if c]}


async def _slate(league: str, date: str) -> dict:
    if league == "pwhl":
        return await feed.pwhl_day(date)
    return await (feed.today_page() if date == feed.today else feed.day(date))


async def _game_from(body: dict) -> dict:
    lg = "pwhl" if body.get("league") == "pwhl" else "nhl"
    date, gid = str(body.get("date") or ""), body.get("id")
    if not DATE.match(date) or not isinstance(gid, int):
        raise HTTPException(400)
    day = await _upstream(_slate(lg, date))
    g = next((dict(x, league=lg) for x in day["games"] if x["id"] == gid), None)
    if not g:
        raise HTTPException(404, "That game isn't on the schedule.")
    return g


@app.post("/api/watching")
async def watching_save(request: Request):
    body = await request.json()
    g = await _game_from(body)
    social.set_watching(request.state.email, g, bool(body.get("on")))
    return {"ok": True}


@app.post("/api/react")
async def react_save(request: Request):
    body = await request.json()
    g = await _game_from(body)
    try:
        social.react(request.state.email, g, str(body.get("event") or ""), body.get("emoji") or None)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True}


@app.get("/api/hidden")
async def hidden_games(request: Request):
    """Games spoiler-free is hiding for this person right now (today's and the previous slate, both leagues), so
    Wire, League and team pages can cover what would give them away. One call instead of four from the page."""
    sp = _settings(request)["spoilers"]
    if not sp["teams"] and not sp["games"]:
        return {"games": []}
    today = feed.opening_day()
    found = []
    for lg in ("nhl", "pwhl"):
        try:
            day = await _slate(lg, today)
            prev = await _slate(lg, day["prev"]) if day.get("prev") and day["prev"] >= _day_before(today) else {"games": []}
        except Exception:
            continue
        found += [dict(g, league=lg) for g in day["games"] + prev["games"] if spoilers.hidden(dict(g, league=lg), sp, today)]
    keep = ("id", "league", "date", "start", "state")
    return {"games": [{**{k: g.get(k) for k in keep}, "away": {"abbr": g["away"]["abbr"]}, "home": {"abbr": g["home"]["abbr"]}}
                      for g in found]}


def _day_before(day: str) -> str:
    return (datetime.fromisoformat(day) - timedelta(days=1)).date().isoformat()


@app.get("/api/pickem")
async def pickem(request: Request, date: str | None = None, leagues: str = "nhl"):
    if date and not DATE.match(date):
        raise HTTPException(400)
    lgs = [lg for lg in ("nhl", "pwhl") if lg in leagues.split(",")] or ["nhl"]
    today = feed.opening_day()
    date = date or today
    days = await asyncio.gather(*[_upstream(_slate(lg, date)) for lg in lgs])
    games = [dict(g, league=lg) for lg, d in zip(lgs, days) for g in d["games"]]
    picks.record_results(games)
    for lg, d in picks.pending(today):  # older picks still waiting for a result (the app was down, say)
        if (d != date or lg not in lgs) and d < today:
            try:
                picks.record_results([dict(g, league=lg) for g in (await _slate(lg, d))["games"]])
            except Exception:
                pass
    games.sort(key=lambda g: (g.get("start") or "", g["id"]))
    names = friend_names()
    me = request.state.email
    return {"date": date, "today": today,
            "prev": max((d["prev"] for d in days if d.get("prev")), default=None),
            "next": min((d["next"] for d in days if d.get("next")), default=None),
            "games": picks.for_games(me, games, names), "board": picks.board(me, names, lgs, today),
            "name": names.get(me, me.split("@")[0])}


@app.post("/api/pickem")
async def pickem_save(request: Request):
    body = await request.json()
    g = await _game_from(body)
    try:
        picks.set_pick(request.state.email, g, body.get("team") or None, bool(body.get("lock")))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True}


WIRE_KINDS = {"move", "news", "insider"}


@app.get("/api/wire")
async def wire_feed(request: Request, kind: str | None = None, team: str | None = None, mine: bool = False,
                    league: str | None = None):
    items = await feed.wire()
    fav = frozenset(_settings(request)["favorites"]) if mine else frozenset()

    def build():
        out = items
        if league in ("nhl", "pwhl"):
            out = [i for i in out if i.get("league", "nhl") == league]
        if kind in WIRE_KINDS:
            out = [i for i in out if i["kind"] == kind]
        if team:
            out = [i for i in out if team.upper() in i["teams"]]
        if mine:
            out = [i for i in out if fav & set(i["teams"])]
        return out[:150]
    return _finished(request, ("wire", league, kind, (team or "").upper(), fav), feed._wire_memo[0] if feed._wire_memo else None, build)


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
