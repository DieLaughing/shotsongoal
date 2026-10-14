"""Pick'em: everyone picks a winner for each game (NHL and PWHL) before puck drop. A right pick is 1 point; one
"lock of the night" per date is worth 2 if right (0 if wrong). Results are filled in from the day slates the app
already loads, so this never asks the leagues for anything extra. Friends' picks show once a game has started."""
from __future__ import annotations

import sqlite3
import threading
from datetime import date as Date, datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS pick (
    email TEXT NOT NULL, league TEXT NOT NULL, game_id INTEGER NOT NULL, date TEXT NOT NULL, start TEXT,
    team TEXT NOT NULL, lock INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL,
    won INTEGER,                                    -- NULL until the game is final
    PRIMARY KEY (email, league, game_id)
);
CREATE INDEX IF NOT EXISTS pick_date ON pick (date);
"""

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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def league(g: dict) -> str:
    return "pwhl" if g.get("league") == "pwhl" else "nhl"


def started(g: dict, now: datetime | None = None) -> bool:
    if g.get("state") not in (None, "pre"):
        return True
    return bool(g.get("start")) and g["start"] <= _iso(now or _now())


def season_of(day: str) -> str:
    """Both leagues' seasons cross New Year: "2026-27" runs July 2026 to June 2027."""
    d = Date.fromisoformat(day)
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y}-{str(y + 1)[2:]}"


def season_bounds(season: str) -> tuple[str, str]:
    y = int(season[:4])
    return f"{y}-07-01", f"{y + 1}-06-30"


def week_start(day: str) -> str:
    d = Date.fromisoformat(day)
    return (d - timedelta(days=d.weekday())).isoformat()  # Monday


def set_pick(email: str, g: dict, team: str | None, lock: bool = False, now: datetime | None = None) -> None:
    """Saves (or with team=None removes) a pick. ValueError with a message people can read when it's not allowed."""
    if g.get("state") in ("postponed",):
        raise ValueError("This game was postponed.")
    if started(g, now):
        raise ValueError("Picks lock at puck drop. This one has started.")
    lg, gid = league(g), g["id"]
    with _lock, _conn:
        if team is None:
            _conn.execute("DELETE FROM pick WHERE email=? AND league=? AND game_id=?", (email, lg, gid))
            return
        if team not in (g["away"]["abbr"], g["home"]["abbr"]):
            raise ValueError("Pick one of the two teams.")
        if lock:
            other = _conn.execute("SELECT league, game_id, start FROM pick WHERE email=? AND date=? AND lock=1 "
                                  "AND NOT (league=? AND game_id=?)", (email, g["date"], lg, gid)).fetchone()
            if other and other[2] and other[2] <= _iso(now or _now()):
                raise ValueError("Your lock of the night is already on a game that has started.")
            _conn.execute("UPDATE pick SET lock=0 WHERE email=? AND date=?", (email, g["date"]))
        _conn.execute("""INSERT INTO pick (email, league, game_id, date, start, team, lock, created) VALUES (?,?,?,?,?,?,?,?)
                         ON CONFLICT (email, league, game_id) DO UPDATE SET team=excluded.team, lock=excluded.lock,
                         start=excluded.start""",
                      (email, lg, gid, g["date"], g.get("start"), team, int(bool(lock)), _iso(now or _now())))


def record_results(games: list[dict]) -> int:
    """Marks picks right or wrong for every final game in the list. Returns how many picks changed."""
    n = 0
    with _lock, _conn:
        for g in games:
            a, h = g["away"].get("score"), g["home"].get("score")
            if g.get("state") != "final" or a is None or h is None or a == h:
                continue
            winner = g["away"]["abbr"] if a > h else g["home"]["abbr"]
            n += _conn.execute("UPDATE pick SET won = (team = ?) WHERE league=? AND game_id=? AND won IS NULL",
                               (winner, league(g), g["id"])).rowcount
    return n


def pending(before: str) -> list[tuple[str, str]]:
    """(league, date) pairs with picks still waiting for a result, up to and including `before`."""
    return [tuple(r) for r in _conn.execute(
        "SELECT DISTINCT league, date FROM pick WHERE won IS NULL AND date <= ? ORDER BY date DESC LIMIT 10", (before,))]


def for_games(email: str, games: list[dict], names: dict[str, str], now: datetime | None = None) -> list[dict]:
    """The games with this person's pick, and everyone's once the game has started."""
    out = []
    # One query for the whole slate, not one per game.
    by_game: dict[tuple, list[dict]] = {}
    if games:
        marks = ",".join("?" * len(games))
        for r in _rows(f"SELECT league, game_id, email, team, lock, won FROM pick WHERE game_id IN ({marks}) ORDER BY created",
                       tuple(g["id"] for g in games)):
            by_game.setdefault((r["league"], r["game_id"]), []).append(r)
    for g in games:
        rows = by_game.get((league(g), g["id"]), [])
        mine = next((r for r in rows if r["email"] == email), None)
        everyone = [{"name": names.get(r["email"], "Someone"), "team": r["team"], "lock": bool(r["lock"]),
                     "me": r["email"] == email} for r in rows if r["email"] in names] if started(g, now) else None
        out.append({**g, "mine": mine["team"] if mine else None, "lock": bool(mine and mine["lock"]),
                    "won": None if not mine or mine["won"] is None else bool(mine["won"]),
                    "picks": everyone, "count": len(rows)})
    return out


def board(email: str, names: dict[str, str], leagues: list[str], today: str) -> dict:
    """Season table, this week and the last night with results, for the given leagues."""
    lo, hi = season_bounds(season_of(today))
    marks = ",".join("?" * len(leagues))
    rows = _rows(f"SELECT email, date, lock, won FROM pick WHERE won IS NOT NULL AND date BETWEEN ? AND ? "
                 f"AND league IN ({marks})", (lo, hi, *leagues))
    rows = [r for r in rows if r["email"] in names]
    week_from = week_start(today)

    def table(picked: list[dict]) -> list[dict]:
        people: dict[str, dict] = {}
        for r in picked:
            p = people.setdefault(r["email"], {"name": names[r["email"]], "me": r["email"] == email, "pts": 0, "w": 0, "l": 0})
            p["w" if r["won"] else "l"] += 1
            p["pts"] += (2 if r["lock"] else 1) if r["won"] else 0
        return sorted(people.values(), key=lambda p: (-p["pts"], -p["w"], p["l"], p["name"].lower()))

    last_day = max((r["date"] for r in rows), default=None)
    return {"season": season_of(today), "table": table(rows), "week": table([r for r in rows if r["date"] >= week_from]),
            "last": {"date": last_day, "table": table([r for r in rows if r["date"] == last_day])} if last_day else None}
