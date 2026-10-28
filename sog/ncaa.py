"""College hockey (NCAA men's and women's) from ESPN's site API, trimmed into the same shapes as sog/nhl.py.

ESPN gives scores, the clock, goals by period, records, poll ranks and where each game streams, but no box scores,
scorers or play-by-play for college games, so a college game page is the scoreboard and a link to ESPN's. Team keys
are "CM-<ESPN id>" (men) and "CW-<ESPN id>" (women): ESPN ids are per school, shared by both teams. Names, conferences
and colours come from sog/data/college.json (tools/college_teams.py).
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from curl_cffi.requests import AsyncSession

from .nhl import ORDINAL

SITE = "https://site.api.espn.com/apis/site/v2/sports/hockey"
STANDINGS = "https://site.api.espn.com/apis/v2/sports/hockey"
LEAGUES = ("ncaam", "ncaaw")
PATH = {"ncaam": "mens-college-hockey", "ncaaw": "womens-college-hockey"}
PREFIX = {"ncaam": "CM-", "ncaaw": "CW-"}
EASTERN = ZoneInfo("America/New_York")
_session: AsyncSession | None = None


async def get(league: str, path: str, base: str = SITE, **params) -> dict:
    global _session
    if _session is None:
        _session = AsyncSession(impersonate="chrome", timeout=20)
    r = await _session.get(f"{base}/{PATH[league]}/{path}", params=params or None)
    r.raise_for_status()
    return r.json()


def key(league: str, tid) -> str:
    return f"{PREFIX[league]}{tid}" if tid not in (None, "") else ""


def league_of(k: str) -> str | None:
    return next((lg for lg, p in PREFIX.items() if (k or "").startswith(p)), None)


def _int(v, default=None):
    if isinstance(v, dict):
        v = v.get("value", v.get("displayValue"))
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def period_label(n: int | None) -> str | None:
    """1-3 -> 1st..3rd, 4 -> OT, 5 -> 2OT."""
    if not n:
        return None
    return ORDINAL.get(n) if n <= 3 else "OT" if n == 4 else f"{n - 3}OT"


def eastern_date(iso: str | None) -> str | None:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(EASTERN).date().isoformat()
    except (AttributeError, ValueError):
        return None


def _utc(iso: str | None) -> str | None:
    """ESPN writes "2026-10-24T23:00Z"; the app's other leagues send seconds too."""
    if not iso:
        return None
    return iso[:-1] + ":00Z" if len(iso) == 17 and iso.endswith("Z") else iso


def _side(c: dict, league: str, ranks: dict[str, int] | None) -> dict:
    t = c.get("team") or {}
    tid = str(t.get("id") or c.get("id") or "")
    rank = ((c.get("curatedRank") or {}).get("current"))
    rank = rank if rank and rank < 99 else (ranks or {}).get(tid)
    record = next((r.get("summary") for r in (c.get("records") or c.get("record") or []) if r.get("type") == "total"), None)
    return {"abbr": key(league, tid), "code": t.get("abbreviation") or "", "name": t.get("shortDisplayName") or t.get("location") or "",
            "score": _int(c.get("score")), "sog": None, "rank": rank, "record": record,
            "periods": [_int(x) or 0 for x in c.get("linescores") or []]}


def parse_event(e: dict, league: str, ranks: dict[str, int] | None = None) -> dict:
    """One game from a scoreboard, a team schedule or a game summary's header, in nhl.parse_score's game shape."""
    c = (e.get("competitions") or [{}])[0]
    status = c.get("status") or e.get("status") or {}
    kind = status.get("type") or {}
    name = kind.get("name") or ""
    state = ("postponed" if name in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED", "STATUS_DELAYED")
             else "final" if kind.get("completed") or kind.get("state") == "post"
             else "live" if kind.get("state") == "in" else "pre")
    sides = {x.get("homeAway"): x for x in c.get("competitors") or []}
    away, home = _side(sides.get("away") or {}, league, ranks), _side(sides.get("home") or {}, league, ranks)
    if state == "pre":
        away["score"] = home["score"] = None
    period = _int(status.get("period"))
    outcome = None
    if state == "final":
        detail = (kind.get("shortDetail") or kind.get("detail") or "").upper()
        outcome = "SO" if "SO" in detail else "OT" if "OT" in detail or (period or 0) > 3 else "REG"
        if away["score"] is not None and away["score"] == home["score"]:
            outcome = "T" if outcome != "SO" else outcome   # a tie stands; a shootout only counts for conference points
    venue = (c.get("venue") or {}).get("fullName") or ""
    nets = []
    for b in c.get("broadcasts") or []:   # scoreboard: {market, names}; summary: one entry per station
        names = b.get("names") or [b.get("station") or ((b.get("media") or {}).get("shortName"))]
        nets += [n for n in names if n and n not in nets]
    link = next((x.get("href") for x in e.get("links") or [] if "summary" in (x.get("rel") or []) or "gamecast" in (x.get("rel") or [])), None)
    return {
        "id": _int(e.get("id")), "league": league, "date": eastern_date(e.get("date") or c.get("date")),
        "start": _utc(e.get("date") or c.get("date")), "type": _int((e.get("season") or {}).get("type"), 2) or 2,
        "state": state, "raw_state": name, "away": away, "home": home,
        "period": period_label(period) if state == "live" else None,
        "clock": status.get("displayClock") if state == "live" else None, "running": state == "live",
        "intermission": name == "STATUS_END_PERIOD", "outcome": outcome, "venue": venue, "recap": None,
        "tickets": None, "networks": nets, "broadcasts": [], "goals": [], "situation": None,
        "neutral": bool(c.get("neutralSite")), "conference": bool(c.get("conferenceCompetition")),
        "note": next((n.get("headline") for n in c.get("notes") or [] if n.get("headline")), None),
        "espn": link or f"https://www.espn.com/{PATH[league]}/game/_/gameId/{e.get('id')}",
    }


def parse_scoreboard(data: dict, league: str, date: str, ranks: dict[str, int] | None = None) -> dict:
    """One date's slate in nhl.parse_score's shape. ESPN's calendar lists every date with games, for the arrows."""
    games = [parse_event(e, league, ranks) for e in data.get("events") or []]
    for g in games:
        g["date"] = date   # ESPN files late games under the date it was asked for
    cal = sorted({eastern_date(d) or "" for lg in data.get("leagues") or [] for d in lg.get("calendar") or [] if isinstance(d, str)} - {""})
    return {"date": date, "league": league, "games": games,
            "prev": max((d for d in cal if d < date), default=None), "next": min((d for d in cal if d > date), default=None)}


def parse_schedule(data: dict, league: str, ranks: dict[str, int] | None = None) -> list[dict]:
    return [parse_event(e, league, ranks) for e in data.get("events") or []]


def parse_rankings(data: dict) -> dict[str, int]:
    """The first poll ESPN lists (USCHO for the men, USCHO / USA Hockey for the women): school id -> rank."""
    for poll in data.get("rankings") or []:
        return {str((r.get("team") or {}).get("id")): r.get("current") for r in poll.get("ranks") or [] if r.get("current")}
    return {}


def parse_standings(data: dict, league: str, ranks: dict[str, int] | None = None,
                    conf_of: dict[str, str | None] | None = None) -> list[dict]:
    """Overall records, grouped by conference. ESPN groups the men; the women's list is one table, so their conference
    comes from `conf_of` (team key -> conference, sog/data/college.json). ESPN's college "points" are always 0, so rows
    sort by win percentage."""
    groups = [(c.get("abbreviation"), c.get("name"), (c.get("standings") or {}).get("entries") or [])
              for c in data.get("children") or []]
    if not groups:
        groups = [(None, None, (data.get("standings") or {}).get("entries") or [])]
    season = ((data.get("standings") or {}).get("seasonDisplayName")
              or next(((c.get("standings") or {}).get("seasonDisplayName") for c in data.get("children") or []), None))
    out = []
    for group, conf_name, entries in groups:
        for e in entries:
            conf = group
            st = {s.get("name"): s for s in e.get("stats") or []}
            t = e.get("team") or {}
            tid = str(t.get("id"))
            v = lambda k: _int(st.get(k, {}).get("value"), 0)
            w, l, ties = v("wins"), v("losses"), v("ties") or v("tiegames")
            gp = v("gamesPlayed") or w + l + ties
            conf = conf or (conf_of or {}).get(key(league, tid))
            out.append({"abbr": key(league, tid), "code": t.get("abbreviation") or "", "name": t.get("displayName") or "",
                        "short": t.get("shortDisplayName") or t.get("location"), "conf": conf, "conf_name": conf_name,
                        "div": conf, "gp": gp, "w": w, "l": l, "t": ties, "otw": v("OTWins"), "otl": v("OTLosses"),
                        "pct": round((w + ties / 2) / gp, 3) if gp else 0.0,
                        "gf": v("pointsFor"), "ga": v("pointsAgainst"), "gd": v("pointsFor") - v("pointsAgainst"),
                        "streak": (st.get("streak") or {}).get("displayValue") if (st.get("streak") or {}).get("displayValue") != "-" else "",
                        "rank": (ranks or {}).get(tid), "season": season, "pts": None})
    out.sort(key=lambda r: (r["conf"] or "", -r["pct"], -r["w"], r["short"] or ""))
    for conf in {r["conf"] for r in out}:
        for i, r in enumerate([r for r in out if r["conf"] == conf], 1):
            r["div_rank"] = i
    return out


def our_score(score: str | None, result: str | None) -> str | None:
    """ESPN writes "4-1" winner first; the app writes the team's own score first ("1-4" for a loss), "OT" kept."""
    parts = (score or "").split(" ", 1)
    nums = parts[0].split("-")
    if result != "L" or len(nums) != 2:
        return score
    return " ".join([f"{nums[1]}-{nums[0]}", *parts[1:]])


def goals(g: dict) -> list[dict]:
    """ESPN names no college scorers, so a goal alert is "the away team's 2nd goal": one key per team per goal, the
    score being what it is when it's seen. A goal taken back never repeats, a re-scored one never doubles."""
    out = []
    a, h = g["away"].get("score") or 0, g["home"].get("score") or 0
    for side, n in (("away", a), ("home", h)):
        for i in range(1, n + 1):
            out.append({"key": f"{side[0]}{i}", "period": g.get("period") or "", "time": "", "team": g[side]["abbr"],
                        "scorer": f"{g[side]['name']} goal", "total": None, "strength": "EV", "empty_net": False,
                        "away": a, "home": h})
    return out
