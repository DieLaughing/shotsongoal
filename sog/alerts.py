"""Push alerts for favourite teams: puck drop, goals, finals and trades.

Each alert has a key (goal:<game>:<goal>) recorded in the sent table, so restarts never repeat one. The first
look at each date after startup only records what's already happened: a deploy mid-game doesn't replay its goals.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from . import home, social, spoilers, watch
from .db import Store
from .push import Pusher

log = logging.getLogger("sog.alerts")

KINDS = ("start", "goals", "final", "trades", "fights")
OFF_BY_DEFAULT = {"fights"}  # opt-in
TRADE_MAX_AGE = timedelta(days=2)


def prefs(settings: dict) -> dict:
    p = settings.get("notify") or {}
    return {k: bool(p.get(k, k not in OFF_BY_DEFAULT)) for k in KINDS}


def rivalry_line(email: str, g: dict, fav: set, friends: dict) -> str:
    """" · Tell Dave." when your team beat a friend's, " · Dave will enjoy this one." when it didn't."""
    rivals = social.rivals(email, g, friends)
    a, h = g["away"], g["home"]
    if not rivals or a.get("score") is None or h.get("score") is None:
        return ""
    winner = a["abbr"] if a["score"] > h["score"] else h["abbr"]
    names = " and ".join(r["name"] for r in rivals[:3])
    return f" · Tell {names}." if winner in fav else f" · {names} will enjoy this one."


class Alerts:
    def __init__(self, store: Store, pusher: Pusher, base_url: str):
        self.store, self.pusher, self.base = store, pusher, base_url
        self.primed_days: set[str] = set()   # scoreboard dates whose existing events are already recorded
        self.primed_trades = False
        self.primed_fights: set[int] = set()  # games whose existing fights are already recorded

    # ---- what happened -------------------------------------------------------------------
    def game_events(self, day: dict) -> list[dict]:
        out = []
        pw = day.get("league") == "pwhl"
        for g in day.get("games") or []:
            a, h, gid = g["away"], g["home"], g["id"]
            teams = [a["abbr"], h["abbr"]]
            code = lambda t: t.get("code") or t["abbr"]  # "BOS", not "PW-BOS"
            # PWHL and NHL ids can collide, so PWHL keys and links carry the league.
            gkey = f"pwhl:{gid}" if pw else gid
            url = f"{self.base}/#/pgame/{gid}" if pw else f"{self.base}/#/game/{gid}"
            matchup = f"{a['name'] or code(a)} at {h['name'] or code(h)}"
            if g["state"] in ("live", "final"):
                out.append({"key": f"start:{gkey}", "kind": "start", "teams": teams, "game": g, "url": url,
                            "title": f"Puck drop: {matchup}", "body": None})
            for x in g.get("goals") or []:
                tags = [t for t in (x["strength"] if x["strength"] != "EV" else "", "EN" if x["empty_net"] else "") if t]
                if not pw:
                    tags += [m for m in [self._milestone(g, x)] if m]
                out.append({"key": f"goal:{gkey}:{x['key']}", "kind": "goals", "teams": teams, "game": g, "url": url,
                            "scorer_team": x["team"],
                            "title": f"{x['team'].removeprefix('PW-')} goal · {code(a)} {x['away']}-{x['home']} {code(h)}",
                            "body": f"{x['scorer']}" + (f" ({x['total']})" if x.get("total") else "")
                                    + f" · {x['period']} {x['time']}" + (f" · {'/'.join(tags)}" if tags else "")})
            if g["state"] == "final" and a.get("score") is not None:
                extra = f" ({g['outcome']})" if g.get("outcome") not in (None, "REG") else ""
                out.append({"key": f"final:{gkey}", "kind": "final", "teams": teams, "game": g, "url": url,
                            "title": f"Final{extra}: {code(a)} {a['score']}, {code(h)} {h['score']}",
                            "body": f"{matchup}"})
        return out

    def _milestone(self, g: dict, x: dict) -> str | None:
        """"🎉 400th career goal" when this goal is one. Career totals are saved before the team plays."""
        saved = self.store.get(f"career:{x['team']}")
        pid = str(x.get("key", "")).rsplit("-", 1)[-1]
        if not saved or not g.get("start") or saved["fetched"] >= g["start"]:
            return None
        player = next((p for p in saved["data"] if str(p.get("id")) == pid), None)
        if not player:
            return None
        goals = [y for y in g.get("goals") or [] if str(y.get("key", "")).rsplit("-", 1)[-1] == pid]
        nth = next((i + 1 for i, y in enumerate(goals) if y["key"] == x["key"]), 0)
        reached = home.milestone_goal(player["goals"], nth)
        return f"🎉 {home.ordinal(reached)} career goal" if reached else None

    def fight_events(self, g: dict, penalties: list[dict]) -> list[dict]:
        """One alert per fight (both players' majors share a period and time)."""
        fights: dict[tuple, list] = {}
        for per in penalties:
            for x in per["items"]:
                if "fight" in (x.get("desc") or "").lower():
                    fights.setdefault((per["period"], x["time"]), []).append(x)
        a, h = g["away"], g["home"]
        code = lambda t: t.get("code") or t["abbr"]
        return [{"key": f"fight:{g['id']}:{period}-{t}", "kind": "fights", "teams": [a["abbr"], h["abbr"]], "game": g,
                 "url": f"{self.base}/#/game/{g['id']}", "title": f"Fight! {code(a)} at {code(h)}",
                 "body": f"{' and '.join(x['player'] or x['team'] for x in xs)} · {period} {t}"}
                for (period, t), xs in fights.items()]

    async def on_fights(self, g: dict, penalties: list[dict]) -> None:
        events = self.fight_events(g, penalties)
        if g["id"] not in self.primed_fights:  # first look after startup: old fights aren't news
            self.store.mark_sent([e["key"] for e in events])
            self.primed_fights.add(g["id"])
            return
        await self._deliver(events)

    def fight_fans(self) -> set[str]:
        """Teams that someone with a phone signed up for alerts wants fight alerts for."""
        emails = {s["email"] for s in self.store.pushes()}
        teams = set()
        for u in self.store.users():  # one read of everyone, not one per subscriber
            if u["email"] not in emails:
                continue
            settings = u.get("settings") or {}
            if prefs(settings)["fights"]:
                teams |= set(settings.get("favorites") or [])
        return teams

    def trade_events(self, items: list[dict]) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - TRADE_MAX_AGE).strftime("%Y-%m-%dT%H:%M:%SZ")
        return [{"key": f"trade:{i['id']}", "kind": "trades", "teams": i["teams"], "url": f"{self.base}/#/wire",
                 "title": f"Trade: {', '.join(i['teams'])}", "body": i["text"]}
                for i in items if i["kind"] == "move" and i.get("trade") and (i.get("time") or "") >= cutoff]

    # ---- sending -----------------------------------------------------------------------------
    async def on_day(self, day: dict) -> None:
        events = self.game_events(day)
        date = f"{day.get('league', 'nhl')}:{day.get('date') or ''}"  # each league's scoreboard primes separately
        if date not in self.primed_days:
            # First look at this date since startup: whatever already happened isn't news.
            self.store.mark_sent([e["key"] for e in events])
            self.primed_days.add(date)
            return
        await self._deliver(events)

    async def on_wire(self, items: list[dict]) -> None:
        events = self.trade_events(items)
        if not self.primed_trades:
            self.store.mark_sent([e["key"] for e in events])
            self.primed_trades = True
            return
        await self._deliver(events)

    async def _deliver(self, events: list[dict]) -> None:
        fresh = [e for e in events if not self.store.was_sent(e["key"])]
        if not fresh:
            return
        self.store.mark_sent([e["key"] for e in fresh])  # before sending: a crash mid-send must not repeat
        subs = self.store.pushes()
        friends = social.friends(self.store.users()) if any(e["kind"] == "final" for e in fresh) else {}
        people = {}
        for s in subs:
            people.setdefault(s["email"], []).append(s)
        everyone = {u["email"]: u for u in self.store.users()}  # one read, not one per subscriber
        for email, mine in people.items():
            user = everyone.get(email) or {}
            settings = user.get("settings") or {}
            fav, want = set(settings.get("favorites") or []), prefs(settings)
            for e in fresh:
                if not want[e["kind"]] or not fav & set(e["teams"]):
                    continue
                if e["kind"] in ("goals", "final") and spoilers.hidden(e["game"], settings.get("spoilers")):
                    continue  # spoiler-free: puck drop still comes, the score never does
                body = e["body"]
                if e["kind"] == "start" and e["game"].get("league") == "pwhl":
                    body = "Where to watch: thepwhl.com"
                elif e["kind"] == "start":
                    w = watch.watch_for(e["game"], settings.get("local"), settings.get("services"))
                    body = f"Watch: {w['app']}" if w.get("app") else w.get("why")
                elif e["kind"] == "final":
                    body = (body or "") + rivalry_line(email, e["game"], fav, friends)
                await self.send(mine, {"title": e["title"], "body": body or "", "url": e["url"], "tag": e["key"]})

    async def send(self, subs: list[dict], payload: dict) -> int:
        delivered = 0
        for s in subs:
            result = await self.pusher.send(s["sub"], payload)
            if result == "gone":
                self.store.remove_push(s["endpoint"])
            delivered += result == "ok"
        return delivered
