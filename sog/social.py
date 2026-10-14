"""Friends on every game: who's watching, emoji reactions on goals and penalties, and rivalries (your team against a
friend's team). Names come from settings.nickname or the email's first part; emails never leave the server.

Kept small on purpose: "watching" rows go a day after the game, reactions at the end of the season (July 1)."""
from __future__ import annotations

import re
import sqlite3
import threading
from datetime import date as Date, datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS watching (
    email TEXT NOT NULL, league TEXT NOT NULL, game_id INTEGER NOT NULL, date TEXT NOT NULL, since TEXT NOT NULL,
    PRIMARY KEY (email, league, game_id)
);
CREATE TABLE IF NOT EXISTS reaction (
    email TEXT NOT NULL, league TEXT NOT NULL, game_id INTEGER NOT NULL, date TEXT NOT NULL,
    event TEXT NOT NULL, emoji TEXT NOT NULL, at TEXT NOT NULL,
    PRIMARY KEY (email, league, game_id, event)
);
CREATE INDEX IF NOT EXISTS reaction_game ON reaction (league, game_id);
"""

EMOJI = ("🔥", "😭", "🤬", "🍺", "🥅")
EVENT = re.compile(r"^[gp]:[\w .'’\-:]{1,80}$")   # g:<period>-<time>-<scorer> / p:<period>-<time>-<player>

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()


def init(conn: sqlite3.Connection) -> None:
    global _conn
    _conn = conn
    with _lock, conn:
        conn.executescript(SCHEMA)


def _rows(sql: str, args: tuple = ()) -> list[dict]:
    cur = _conn.cursor()
    cur.row_factory = sqlite3.Row
    return [dict(r) for r in cur.execute(sql, args)]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def league(g: dict) -> str:
    return "pwhl" if g.get("league") == "pwhl" else "nhl"


# ---- people --------------------------------------------------------------------------------
def display_name(email: str, settings: dict | None) -> str:
    return (settings or {}).get("nickname") or email.split("@")[0]


def friends(users: list[dict], admin: str | None = None) -> dict[str, dict]:
    """Approved people: email -> {name, favorites}."""
    out = {u["email"]: {"name": display_name(u["email"], u.get("settings")), "favorites": (u.get("settings") or {}).get("favorites") or []}
           for u in users if u.get("status") == "approved" or u["email"] == admin}
    return out


def rivals(email: str, g: dict, people: dict[str, dict]) -> list[dict]:
    """Friends whose main team (their first favourite in this league) is the other side from one of yours."""
    sides = {g["away"]["abbr"], g["home"]["abbr"]}
    mine = set((people.get(email) or {}).get("favorites") or []) & sides
    if not mine:
        return []
    other = sides - mine
    out = []
    for e, p in people.items():
        if e == email:
            continue
        main = next((t for t in p["favorites"] if t.startswith("PW-") == (league(g) == "pwhl")), None)
        if main in other:
            out.append({"name": p["name"], "team": main})
    return out


# ---- watching and reactions ----------------------------------------------------------------
def set_watching(email: str, g: dict, on: bool) -> None:
    with _lock, _conn:
        if on:
            _conn.execute("INSERT OR IGNORE INTO watching (email, league, game_id, date, since) VALUES (?,?,?,?,?)",
                          (email, league(g), g["id"], g.get("date") or "", _now()))
        else:
            _conn.execute("DELETE FROM watching WHERE email=? AND league=? AND game_id=?", (email, league(g), g["id"]))


def react(email: str, g: dict, event: str, emoji: str | None) -> None:
    if not EVENT.match(event or ""):
        raise ValueError("Unknown moment.")
    if emoji is not None and emoji not in EMOJI:
        raise ValueError("Unknown reaction.")
    if g.get("state") not in ("live", "final"):
        raise ValueError("Nothing to react to yet.")
    with _lock, _conn:
        if emoji is None:
            _conn.execute("DELETE FROM reaction WHERE email=? AND league=? AND game_id=? AND event=?",
                          (email, league(g), g["id"], event))
        else:
            _conn.execute("""INSERT INTO reaction (email, league, game_id, date, event, emoji, at) VALUES (?,?,?,?,?,?,?)
                             ON CONFLICT (email, league, game_id, event) DO UPDATE SET emoji=excluded.emoji, at=excluded.at""",
                          (email, league(g), g["id"], g.get("date") or "", event, emoji, _now()))


def watchers(games: list[dict], email: str, people: dict[str, dict]) -> dict[str, list[dict]]:
    """"nhl:<id>" -> [{name, me}] for a slate, for the cards on Tonight."""
    out: dict[str, list[dict]] = {}
    if not games:
        return out
    wanted = {f"{league(g)}:{g['id']}" for g in games}
    marks = ",".join("?" * len(games))
    # One query for the whole slate, not one per game.
    for r in _rows(f"SELECT league, game_id, email FROM watching WHERE game_id IN ({marks}) ORDER BY since",
                   tuple(g["id"] for g in games)):
        key = f"{r['league']}:{r['game_id']}"
        if key in wanted and r["email"] in people:
            out.setdefault(key, []).append({"name": people[r["email"]]["name"], "me": r["email"] == email})
    return out


def for_game(email: str, g: dict, people: dict[str, dict]) -> dict:
    counts: dict[str, dict[str, int]] = {}
    mine: dict[str, str] = {}
    for r in _rows("SELECT email, event, emoji FROM reaction WHERE league=? AND game_id=?", (league(g), g["id"])):
        if r["email"] not in people:
            continue
        counts.setdefault(r["event"], {}).setdefault(r["emoji"], 0)
        counts[r["event"]][r["emoji"]] += 1
        if r["email"] == email:
            mine[r["event"]] = r["emoji"]
    watching = watchers([g], email, people).get(f"{league(g)}:{g['id']}", [])
    return {"watching": watching, "me_watching": any(w["me"] for w in watching), "reactions": counts, "mine": mine,
            "rivals": rivals(email, g, people), "emoji": list(EMOJI)}


def cleanup(today: str) -> None:
    """Watching rows a day after the game; reactions once a new season starts (July 1)."""
    d = Date.fromisoformat(today)
    season_start = f"{d.year if d.month >= 7 else d.year - 1}-07-01"
    with _lock, _conn:
        _conn.execute("DELETE FROM watching WHERE date < ?", ((d - timedelta(days=1)).isoformat(),))
        _conn.execute("DELETE FROM reaction WHERE date < ?", (season_start,))
