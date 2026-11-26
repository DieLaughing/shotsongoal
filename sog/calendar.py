"""The Calendar page (#/calendar/<YYYY-MM>, GET /api/month): a month of hockey at a glance, to jump to any day.
(Not the calendar feeds: those are sog/ics.py and /cal.)

Built from what the app already keeps: the saved NHL team schedules (all 32, kept fresh by the warm-up) and the PWHL
season feed. It never waits on a league. Each day carries how many games there are, your teams' games (with the
scores, so the page can show W/L where spoiler-free allows) and any showcase game (Winter Classic, Global Series...).
On top: the season's moments, dates the NHL keeps every year, and the Christmas break worked out from the schedule.
"""
from __future__ import annotations

from datetime import date, timedelta

# Recurring moments: (key, name, line, first day MM-DD, last day MM-DD). A range may run into the next year.
MOMENTS = (
    ("freeze", "Holiday roster freeze", "No trades or waivers until the 28th", "12-20", "12-27"),
    ("wjc", "World Juniors", "The under-20 world championship", "12-26", "01-05"),
)


def month_days(month: str) -> list[date]:
    y, m = map(int, month.split("-"))
    first = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return [first + timedelta(days=i) for i in range((nxt - first).days)]


def shift(month: str, by: int) -> str:
    y, m = map(int, month.split("-"))
    k = y * 12 + m - 1 + by
    return f"{k // 12:04d}-{k % 12 + 1:02d}"


def _slim(g: dict) -> dict:
    side = lambda t: {"abbr": t.get("abbr"), "score": t.get("score")}
    return {"id": g["id"], "league": g.get("league", "nhl"), "date": g["date"], "start": g.get("start"),
            "state": g.get("state"), "away": side(g["away"]), "home": side(g["home"]), "event": g.get("event"),
            "venue": g.get("venue")}


def moments(month: str, nhl_days: dict[str, int] | None) -> list[dict]:
    """The recurring moments that touch this month, with their full date range. `nhl_days` (date -> NHL games, or None
    when NHL isn't shown) decides the Christmas break: marked only when those days really have no games."""
    days = month_days(month)
    y = days[0].year
    out = []
    for key, name, line, a, b in MOMENTS:
        for start_year in (y - 1, y):
            first = date.fromisoformat(f"{start_year}-{a}")
            last = date.fromisoformat(f"{start_year + (b < a)}-{b}")
            if first <= days[-1] and last >= days[0]:
                out.append({"key": key, "name": name, "line": line, "from": first.isoformat(), "to": last.isoformat()})
    if nhl_days is not None and days[0].month == 12 and any(nhl_days.values()) and not nhl_days.get(f"{y}-12-25"):
        # The run of game-free days around Christmas, read from the schedule: it moves (Dec 23-25 in 2026-27).
        xmas = date(y, 12, 25)
        a = b = xmas
        while a.day > 1 and not nhl_days.get((a - timedelta(days=1)).isoformat()):
            a -= timedelta(days=1)
        while b.day < 31 and not nhl_days.get((b + timedelta(days=1)).isoformat()):
            b += timedelta(days=1)
        out.append({"key": "break", "name": "Christmas break", "line": "No NHL games", "from": a.isoformat(), "to": b.isoformat()})
    return sorted(out, key=lambda m: m["from"])


def build(month: str, games: list[dict], favorites: list[str], today: str, leagues: list[str],
          own: list[dict] = ()) -> dict:
    """The page's data for one month. `games`: every game the shown leagues have this season (each with `league`);
    they make the counts and the showcase badges. `own`: your teams' games from leagues that aren't shown (a PWHL or
    college favourite with the NHL on): your teams are always on the calendar, whatever the league switch says."""
    days = {d.isoformat(): {"n": 0, "mine": [], "events": []} for d in month_days(month)}
    rank = {abbr: i for i, abbr in enumerate(favorites)}   # your first team colours a day two of them play
    seen, mine_seen = set(), set()

    def add_mine(g, key):
        if key not in mine_seen and (g["away"].get("abbr") in rank or g["home"].get("abbr") in rank):
            mine_seen.add(key)
            days[g["date"]]["mine"].append(_slim(g))
    for g in games:
        key = (g.get("league", "nhl"), g["id"])
        if key in seen or g.get("date") not in days:
            continue
        seen.add(key)
        day = days[g["date"]]
        day["n"] += 1
        add_mine(g, key)
        if g.get("event"):
            day["events"].append(_slim(g))
    for g in own:
        if g.get("date") in days:
            add_mine(g, (g.get("league", "nhl"), g["id"]))
    best = lambda g: min(rank.get(g["away"]["abbr"], 99), rank.get(g["home"]["abbr"], 99))
    for day in days.values():
        day["mine"].sort(key=lambda g: (best(g), g.get("start") or ""))
    dates = sorted(g["date"] for g in [*games, *own] if g.get("date"))
    nhl_days = {d: sum(1 for g in games if g.get("league", "nhl") == "nhl" and g.get("date") == d) for d in days} \
        if "nhl" in leagues else None
    return {"month": month, "today": today, "leagues": leagues, "days": days, "moments": moments(month, nhl_days),
            # Months you can step to: as far as the seasons shown have games.
            "prev": shift(month, -1) if dates and dates[0][:7] < month else None,
            "next": shift(month, 1) if dates and dates[-1][:7] > month else None}
