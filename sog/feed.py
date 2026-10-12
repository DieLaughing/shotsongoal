"""The saved copy of NHL data, and the pollers that keep it fresh.

Pages only ever read from the saved copy. A key that's missing or stale is fetched once, however many
people ask at the same moment, and an upstream failure falls back to the last good copy.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import nhl, pwhl, wire
from .db import Store, parse_iso

log = logging.getLogger("sog.feed")

LIVE_POLL = 10            # seconds between score refreshes while a game is on (or about to start)
IDLE_POLL = 300           # ... and otherwise
DETAIL_POLL = 20          # a live game's page, only while someone has looked at it recently
VIEW_WINDOW = 300
STANDINGS_TTL = timedelta(minutes=15)
NEWS_TTL = timedelta(minutes=10)      # ESPN moves and headlines, Sportsnet
INSIDER_TTL = timedelta(minutes=2)    # Bluesky: rumours move fast
WIRE_POLL = 120
WIRE_MAX_AGE = timedelta(days=30)
PWHL_LIVE = timedelta(seconds=15)     # PWHL scoreboard while a game is on or about to start
PWHL_IDLE = timedelta(minutes=30)     # ... and otherwise
PWHL_TEAM_IDS = {"BOS": 1, "MIN": 2, "MTL": 3, "NY": 4, "OTT": 5, "TOR": 6, "SEA": 8, "VAN": 9,
                 "DET": 10, "HAM": 11, "VGS": 12, "SJ": 13}
EASTERN = ZoneInfo("America/New_York")
INSIDER_DEFAULTS = {"nhl": wire.DEFAULT_INSIDERS, "pwhl": wire.PWHL_INSIDERS}


def eastern_today() -> str:
    return datetime.now(EASTERN).date().isoformat()


class Feed:
    def __init__(self, store: Store):
        self.store = store
        self.locks: dict[str, asyncio.Lock] = {}
        self.viewed: dict[int, float] = {}   # game id -> last time someone opened its page
        self.today: str | None = None
        self.alerts = None                   # set by the app: told about every scoreboard and Wire refresh

    async def _fetch(self, key: str, source: str, fetch, ttl) -> dict | list:
        """Fetch, save and return. ttl may be a function of the parsed data."""
        lock = self.locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self.store.get(key)
            if hit and hit["fresh"]:
                return hit["data"]  # someone else fetched it while we waited
            try:
                data = await fetch()
            except Exception as exc:
                log.warning("%s failed: %r", key, exc)
                self.store.record_run(source, False, f"{type(exc).__name__}: {exc}"[:300])
                if hit:
                    return hit["data"]
                raise
            self.store.put(key, data, ttl(data) if callable(ttl) else ttl)
            self.store.record_run(source, True)
            return data

    async def cached(self, key: str, source: str, fetch, ttl) -> dict | list:
        hit = self.store.get(key)
        if hit and hit["fresh"]:
            return hit["data"]
        return await self._fetch(key, source, fetch, ttl)

    # ---- what pages ask for -------------------------------------------------------
    async def day(self, date: str) -> dict:
        async def fetch():
            return nhl.parse_score(await nhl.get(f"score/{date}"))
        return await self.cached(f"score:{date}", "score", fetch, lambda d: _day_ttl(d, date))

    async def game(self, game_id: int) -> dict:
        self.viewed[game_id] = time.time()
        return await self._load_game(game_id)

    async def _load_game(self, game_id: int) -> dict:
        async def fetch():
            landing, rail, box, pbp = await asyncio.gather(
                nhl.get(f"gamecenter/{game_id}/landing"),
                nhl.get(f"gamecenter/{game_id}/right-rail"),
                nhl.get(f"gamecenter/{game_id}/boxscore"),
                nhl.get(f"gamecenter/{game_id}/play-by-play"), return_exceptions=True)
            if isinstance(landing, Exception):
                raise landing
            detail = nhl.parse_detail(landing, None if isinstance(rail, Exception) else rail,
                                      None if isinstance(box, Exception) else box)
            plays = {"shots": [], "situation": None} if isinstance(pbp, Exception) else nhl.parse_pbp(pbp)
            return {**detail, "shotmap": plays["shots"], "situation": plays["situation"], "recap": nhl.recap(detail)}
        return await self.cached(f"game:{game_id}", "game", fetch, _game_ttl)

    async def standings(self) -> list:
        async def fetch():
            return nhl.parse_standings(await nhl.get("standings/now"))
        return await self.cached("standings", "standings", fetch, STANDINGS_TTL)

    async def team(self, abbr: str) -> dict:
        async def schedule():
            return nhl.parse_club_schedule(await nhl.get(f"club-schedule-season/{abbr}/now"))

        async def roster():
            return nhl.parse_roster(await nhl.get(f"roster/{abbr}/current"))

        async def stats():
            return nhl.parse_club_stats(await nhl.get(f"club-stats/{abbr}/now"))

        sched, rost, st = await asyncio.gather(
            self.cached(f"team:{abbr}:schedule", "team", schedule, timedelta(minutes=30)),
            self.cached(f"team:{abbr}:roster", "team", roster, timedelta(hours=12)),
            self.cached(f"team:{abbr}:stats", "team", stats, timedelta(hours=1)),
            return_exceptions=True)
        return {"schedule": [] if isinstance(sched, Exception) else sched,
                "roster": [] if isinstance(rost, Exception) else rost,
                "stats": {"skaters": [], "goalies": []} if isinstance(st, Exception) else st}

    async def wire(self) -> list[dict]:
        """Every source merged, newest first. A failing source just drops out until it's back."""
        jobs = [self.cached("wire:moves", "wire:espn-moves", wire.fetch_moves, NEWS_TTL),
                self.cached("wire:espn", "wire:espn-news", wire.fetch_espn_news, NEWS_TTL),
                self.cached("wire:sportsnet", "wire:sportsnet", wire.fetch_sportsnet, NEWS_TTL),
                self.cached("wire:pwhl-news", "wire:pwhl-news", wire.fetch_pwhl_news, NEWS_TTL)]
        for ins in self.store.insiders(INSIDER_DEFAULTS):
            h, label, league = ins["handle"], ins["label"], ins.get("league") or "nhl"
            jobs.append(self.cached(f"wire:bsky:{h}", "wire:bluesky",
                                    lambda h=h, label=label, league=league: wire.fetch_bsky(h, label, league), INSIDER_TTL))
        results = await asyncio.gather(*jobs, return_exceptions=True)
        cutoff = (datetime.now(timezone.utc) - WIRE_MAX_AGE).strftime("%Y-%m-%dT%H:%M:%SZ")
        seen, items = set(), []
        for r in results:
            if isinstance(r, Exception):
                continue
            for item in r:
                if item["id"] in seen or not item.get("time") or item["time"] < cutoff:
                    continue
                seen.add(item["id"])
                items.append(item)
        items.sort(key=lambda i: i["time"], reverse=True)
        return items[:500]

    # ---- PWHL (HockeyTech) ------------------------------------------------------------------
    async def pwhl_seasons(self) -> list[dict]:
        async def fetch():
            return pwhl.parse_seasons(await pwhl.get(feed="modulekit", view="seasons"))
        return await self.cached("pwhl:seasons", "pwhl", fetch, timedelta(hours=12))

    async def pwhl_games(self) -> list[dict]:
        """Every game from last season to the end of this one: one feed call serves days, teams and alerts."""
        async def fetch():
            types = {s["id"]: s["type"] for s in await self.pwhl_seasons()}
            data = await pwhl.get(feed="modulekit", view="scorebar", numberofdaysback=400, numberofdaysahead=240)
            return pwhl.parse_scorebar(data, types)
        return await self.cached("pwhl:games", "pwhl", fetch, lambda games: PWHL_LIVE if _busy({"games": games}) else PWHL_IDLE)

    async def pwhl_day(self, date: str | None) -> dict:
        return {**pwhl.day(await self.pwhl_games(), date or eastern_today()), "league": "pwhl"}

    async def pwhl_game(self, game_id: int) -> dict:
        self.viewed[-game_id] = time.time()  # PWHL ids are small; keep them apart from NHL ids
        return await self._load_pwhl_game(game_id)

    async def _load_pwhl_game(self, game_id: int) -> dict:
        async def fetch():
            summary, pxp = await asyncio.gather(pwhl.get(feed="gc", game_id=game_id, tab="gamesummary"),
                                                pwhl.get(feed="gc", game_id=game_id, tab="pxpverbose"),
                                                return_exceptions=True)
            if isinstance(summary, Exception):
                raise summary
            base = next((g for g in await self.pwhl_games() if g["id"] == game_id), None)
            if not base:
                raise LookupError(f"PWHL game {game_id} not on the schedule")
            detail = pwhl.parse_detail(summary, None if isinstance(pxp, Exception) else pxp, base)
            return {**detail, "recap": nhl.recap(detail)}
        return await self.cached(f"pwhl:game:{game_id}", "pwhl", fetch, _game_ttl)

    async def _pwhl_season_with_games(self, kind: int = 2) -> dict | None:
        """This season, or last season while this one hasn't started (so standings aren't all zeros)."""
        seasons = await self.pwhl_seasons()
        today = eastern_today()
        cur = pwhl.current_season(seasons, today, kind)
        if cur and (cur["start"] or "") > today:
            done = [x for x in seasons if x["type"] == kind and (x["end"] or "") < today]
            return max(done, key=lambda x: x["end"] or "") if done else cur
        return cur

    async def pwhl_standings(self) -> list[dict]:
        async def fetch():
            season = await self._pwhl_season_with_games()
            rows = pwhl.parse_standings(await pwhl.get(feed="modulekit", view="statviewtype", type="standings",
                                                       stat="conference", season_id=season["id"]))
            return [{**r, "season": season["name"]} for r in rows]
        return await self.cached("pwhl:standings", "pwhl", fetch, STANDINGS_TTL)

    async def pwhl_team(self, key: str) -> dict:
        code = key.removeprefix(pwhl.PREFIX)
        tid = PWHL_TEAM_IDS.get(code)

        async def roster():
            season = await self._pwhl_season_with_games()
            rows = pwhl.parse_roster(await pwhl.get(feed="modulekit", view="roster", team_id=tid, season_id=season["id"]))
            if not rows:  # an expansion team before its first season: try the upcoming season's list
                cur = pwhl.current_season(await self.pwhl_seasons(), eastern_today())
                if cur and cur["id"] != season["id"]:
                    rows = pwhl.parse_roster(await pwhl.get(feed="modulekit", view="roster", team_id=tid, season_id=cur["id"]))
            return rows

        async def stats():
            season = await self._pwhl_season_with_games()
            sk, gl = await asyncio.gather(
                pwhl.get(feed="modulekit", view="statviewtype", type="topscorers", season_id=season["id"], team_id=tid, first=0, limit=30),
                pwhl.get(feed="modulekit", view="statviewtype", type="topgoalies", season_id=season["id"], team_id=tid, first=0, limit=10))
            return pwhl.parse_scorers((sk.get("SiteKit") or {}).get("Statviewtype"), (gl.get("SiteKit") or {}).get("Statviewtype"))

        games, rost, st = await asyncio.gather(
            self.pwhl_games(),
            self.cached(f"pwhl:team:{code}:roster", "pwhl", roster, timedelta(hours=12)),
            self.cached(f"pwhl:team:{code}:stats", "pwhl", stats, timedelta(hours=1)),
            return_exceptions=True)
        sched = [] if isinstance(games, Exception) else [g for g in games if key in (g["away"]["abbr"], g["home"]["abbr"])]
        return {"schedule": sched, "roster": [] if isinstance(rost, Exception) else rost,
                "stats": {"skaters": [], "goalies": []} if isinstance(st, Exception) else st}

    async def pwhl_name_changes(self) -> list[dict]:
        """The current season's team list from the league, compared with the app's own (sog/teams.py)."""
        from .teams import PWHL
        season = pwhl.current_season(await self.pwhl_seasons(), eastern_today())
        if not season:
            return []
        return pwhl.name_changes(await pwhl.get(feed="modulekit", view="teamsbyseason", season_id=season["id"]), PWHL)

    async def poll_pwhl(self) -> dict:
        """Today's PWHL games for alerts. Live games get their goals from the game summary, which the
        scoreboard lacks."""
        day = await self.pwhl_day(None)
        for g in day["games"]:
            if g["state"] in ("live", "final") and (g["state"] == "live" or not self.store.get(f"pwhl:game:{g['id']}")):
                try:
                    d = await self._load_pwhl_game(g["id"])
                    g["goals"] = [{"key": f"{per['period']}-{x['time']}-{x['scorer']}", "period": per["period"], "time": x["time"],
                                   "team": x["team"], "scorer": x["scorer"], "total": x["total"], "strength": x["strength"],
                                   "empty_net": x["modifier"] == "empty-net", "away": x["away"], "home": x["home"]}
                                  for per in d["scoring"] for x in per["goals"]]
                except Exception:
                    pass
        return day

    # ---- pollers --------------------------------------------------------------------
    async def poll_today(self) -> dict:
        """Refresh today's scoreboard (the NHL's own 'now', in Eastern time)."""
        async def fetch():
            return nhl.parse_score(await nhl.get("score/now"))
        data = await self._fetch("score:now", "score", fetch, timedelta(seconds=LIVE_POLL - 1))
        if data.get("date"):
            self.today = data["date"]
            self.store.put(f"score:{data['date']}", data, timedelta(seconds=LIVE_POLL * 3))
        return data

    async def loop(self) -> None:
        last_idle = last_standings = last_wire = last_pwhl = 0.0
        last_detail: dict[int, float] = {}
        while True:
            try:
                now = time.time()
                hit = self.store.get("score:now")
                busy = bool(hit) and _busy(hit["data"])
                if busy or now - last_idle >= IDLE_POLL:
                    day = await self.poll_today()
                    last_idle = now
                    busy = _busy(day)
                    if self.alerts:
                        await self.alerts.on_day(day)
                    # A late game can run past midnight Eastern: keep yesterday fresh until it ends.
                    if day.get("prev"):
                        prev = self.store.get(f"score:{day['prev']}")
                        if not prev or any(g["state"] == "live" for g in prev["data"]["games"]):
                            prev_day = await self._fetch(f"score:{day['prev']}", "score",
                                                         lambda: _get_day(day["prev"]), timedelta(seconds=LIVE_POLL * 3))
                            busy = busy or any(g["state"] == "live" for g in prev_day["games"])
                            if self.alerts:  # a West Coast game can end after the NHL's "today" rolls over
                                await self.alerts.on_day(prev_day)
                    # Live game pages that someone is watching.
                    for g in day.get("games", []):
                        gid = g["id"]
                        watched = now - self.viewed.get(gid, 0) < VIEW_WINDOW
                        if g["state"] == "live" and watched and now - last_detail.get(gid, 0) >= DETAIL_POLL:
                            last_detail[gid] = now
                            await self._refresh_game(gid)
                pw = self.store.get("pwhl:games")
                pw_busy = bool(pw) and _busy({"games": pw["data"]})
                if now - last_pwhl >= (PWHL_LIVE if pw_busy else PWHL_IDLE).total_seconds():
                    last_pwhl = now
                    pday = await self.poll_pwhl()
                    busy = busy or _busy(pday)
                    if self.alerts:
                        await self.alerts.on_day(pday)
                if now - last_wire >= WIRE_POLL:
                    last_wire = now
                    items = await self.wire()
                    if self.alerts:
                        await self.alerts.on_wire(items)
                if now - last_standings >= STANDINGS_TTL.total_seconds():
                    last_standings = now
                    await self._fetch("standings", "standings", _get_standings, STANDINGS_TTL)
            except Exception:
                log.exception("poll loop error")
            await asyncio.sleep(LIVE_POLL if busy else 30)

    async def _refresh_game(self, gid: int) -> None:
        key = f"game:{gid}"
        hit = self.store.get(key)
        if hit:  # mark stale so _fetch goes upstream
            self.store.put(key, hit["data"], timedelta(seconds=-1))
        try:
            await self._load_game(gid)  # not game(): the poller isn't a viewer
        except Exception:
            pass


async def _get_day(date: str) -> dict:
    return nhl.parse_score(await nhl.get(f"score/{date}"))


async def _get_standings() -> list:
    return nhl.parse_standings(await nhl.get("standings/now"))


def _busy(day: dict) -> bool:
    """A game is live, or one starts within 20 minutes."""
    soon = datetime.now(timezone.utc) + timedelta(minutes=20)
    for g in day.get("games", []):
        if g["state"] == "live":
            return True
        if g["state"] == "pre" and g.get("start") and parse_iso(g["start"]) <= soon:
            return True
    return False


def _day_ttl(day: dict, date: str) -> timedelta | None:
    games = day.get("games") or []
    today = datetime.now(timezone.utc).date().isoformat()
    if date < today and all(g["state"] in ("final", "postponed") for g in games):
        return None  # finished days never change
    if any(g["state"] == "live" for g in games):
        return timedelta(seconds=LIVE_POLL * 3)
    return timedelta(minutes=10 if date <= today else 60)


def _game_ttl(detail: dict) -> timedelta | None:
    g = detail["game"]
    if g["state"] == "live":
        return timedelta(seconds=DETAIL_POLL)
    if g["state"] == "final":
        started = parse_iso(g["start"]) if g.get("start") else datetime.now(timezone.utc)
        # Stars and stats settle in the hour after the horn; after that it's history.
        return None if datetime.now(timezone.utc) - started > timedelta(hours=8) else timedelta(minutes=10)
    return timedelta(minutes=30)
