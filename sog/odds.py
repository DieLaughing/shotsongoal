"""Game odds, for fun only: who's favoured (DraftKings moneyline, from the NHL's own scoreboard) and how many goals
are expected (the over/under, from ESPN's scoreboard). Nothing here links to a sportsbook.

The NHL drops a game's odds once it starts, so the last line seen before puck drop is saved (game_odds). That
saved line decides who was the underdog for "Upset!" and the Pick'em upset bonus. Every row is also kept in
memory, so pages never query for odds.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone

from .wire import ESPN_ABBR, _get as get_url

SCHEMA = """
CREATE TABLE IF NOT EXISTS game_odds (
    league TEXT NOT NULL, game_id INTEGER NOT NULL, date TEXT NOT NULL,
    away_ml INTEGER, home_ml INTEGER,               -- American odds: -118 favoured, +102 underdog
    total REAL,                                     -- expected goals (over/under)
    updated TEXT NOT NULL,
    PRIMARY KEY (league, game_id)
);
"""
HIGH_TOTAL = 7.0   # most NHL lines are 6.5 now; 7+ means the books expect a high-scoring game
LOW_TOTAL = 5.5    # ... and 5.5 or less a low-scoring one

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()
_saved: dict[tuple[str, int], dict] = {}


def init(conn: sqlite3.Connection) -> None:
    global _conn
    _conn = conn
    with _lock, conn:
        conn.executescript(SCHEMA)
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    _saved.clear()
    for r in cur.execute("SELECT league, game_id, away_ml, home_ml, total FROM game_odds"):
        _saved[(r["league"], r["game_id"])] = {"away_ml": r["away_ml"], "home_ml": r["home_ml"], "total": r["total"]}


def american(v) -> int | None:
    """"-118" / "+102" / "EVEN" -> int."""
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v or "").strip().upper()
    if s in ("EVEN", "EV"):
        return 100
    try:
        return int(s.replace("+", ""))
    except ValueError:
        return None


def _implied(ml: int) -> float:
    return -ml / (-ml + 100) if ml < 0 else 100 / (ml + 100)


def chances(away_ml: int, home_ml: int) -> tuple[int, int]:
    """Win chances in percent, with the bookmaker's cut taken out so they add up to 100."""
    a, h = _implied(away_ml), _implied(home_ml)
    pa = round(100 * a / (a + h))
    return pa, 100 - pa


def underdog(league: str, game_id: int) -> str | None:
    """"away" / "home" for the side the last pre-game line had as the underdog, None if unknown or even."""
    o = _saved.get((league, game_id))
    if not o or o["away_ml"] is None or o["home_ml"] is None or o["away_ml"] == o["home_ml"]:
        return None
    return "away" if o["away_ml"] > o["home_ml"] else "home"


def _save(league: str, game_id: int, date: str, **changes) -> None:
    key = (league, game_id)
    old = _saved.get(key) or {"away_ml": None, "home_ml": None, "total": None}
    new = {**old, **changes}
    if new == old and key in _saved:
        return
    _saved[key] = new
    with _lock, _conn:
        _conn.execute("""INSERT INTO game_odds (league, game_id, date, away_ml, home_ml, total, updated) VALUES (?,?,?,?,?,?,?)
                         ON CONFLICT (league, game_id) DO UPDATE SET away_ml=excluded.away_ml, home_ml=excluded.home_ml,
                         total=excluded.total, updated=excluded.updated""",
                      (league, game_id, date, new["away_ml"], new["home_ml"], new["total"],
                       datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))


def note(games: list[dict]) -> None:
    """Save the line of every NHL game that hasn't started (called with each scoreboard refresh). Writes only on change."""
    for g in games:
        o = g.get("odds")
        if g.get("state") == "pre" and o:
            _save("nhl", g["id"], g.get("date") or "", away_ml=o["away"], home_ml=o["home"])


def note_totals(games: list[dict], totals: dict[tuple[str, str], float]) -> None:
    """totals: (away abbr, home abbr) -> expected goals, matched to the day's NHL games that haven't started."""
    for g in games:
        t = totals.get((g["away"]["abbr"], g["home"]["abbr"]))
        if g.get("state") == "pre" and t is not None:
            _save("nhl", g["id"], g.get("date") or "", total=t)


ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"


async def fetch_totals(date: str) -> dict[tuple[str, str], float]:
    """ESPN's scoreboard for a day: (away abbr, home abbr) -> the over/under, for games that have one."""
    data = (await get_url(ESPN_SCOREBOARD, dates=date.replace("-", ""))).json()
    return parse_totals(data)


def parse_totals(data: dict) -> dict[tuple[str, str], float]:
    out = {}
    for e in data.get("events") or []:
        comp = (e.get("competitions") or [{}])[0]
        side = {c.get("homeAway"): ESPN_ABBR.get(c["team"]["abbreviation"], c["team"]["abbreviation"])
                for c in comp.get("competitors") or [] if (c.get("team") or {}).get("abbreviation")}
        total = next((o.get("overUnder") for o in comp.get("odds") or [] if o.get("overUnder") is not None), None)
        if total is not None and "away" in side and "home" in side:
            out[(side["away"], side["home"])] = float(total)
    return out


def attach(games: list[dict]) -> list[dict]:
    """Adds g["odds"] (or None) to NHL games: favourite, win chances, expected goals and, once final, whether it was an
    upset. Before puck drop the scoreboard's own line wins; after it the saved one is all there is."""
    for g in games:
        if g.get("league") == "pwhl":
            continue
        saved = _saved.get(("nhl", g["id"])) or {}
        live = g.get("odds") if g.get("state") == "pre" else None
        a_ml = live["away"] if live else saved.get("away_ml")
        h_ml = live["home"] if live else saved.get("home_ml")
        total = saved.get("total")
        if a_ml is None or h_ml is None:
            g["odds"] = {"total": total, "scoring": scoring(total)} if total is not None else None
            continue
        pa, ph = chances(a_ml, h_ml)
        fav = "away" if a_ml < h_ml else "home" if h_ml < a_ml else None
        out = {"away_ml": a_ml, "home_ml": h_ml, "away_pct": pa, "home_pct": ph,
               "fav": g[fav]["abbr"] if fav else None, "total": total, "scoring": scoring(total), "upset": None}
        a, h = g["away"].get("score"), g["home"].get("score")
        if g.get("state") == "final" and fav and a is not None and h is not None and a != h:
            out["upset"] = (a > h) != (fav == "away")
        g["odds"] = out
    return games


def scoring(total: float | None) -> str | None:
    if total is None:
        return None
    return "high" if total >= HIGH_TOTAL else "low" if total <= LOW_TOTAL else "average"
