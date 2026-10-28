"""The "your team" card on Tonight: one summary per favourite team, from data the app already caches (the team's
schedule and the standings). Pure functions, so tests can feed them fixtures."""
from __future__ import annotations

from datetime import date, timedelta

WEEK = 7  # days in "Last 7 days"
BREAK = 60  # days without a game that separate two seasons (the PWHL feed spans more than one)


def _days(a: str | None, b: str | None) -> int:
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except (TypeError, ValueError):
        return 0


def ordinal(n: int | None) -> str:
    if not n:
        return ""
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _sides(g: dict, abbr: str) -> tuple[dict, dict, bool]:
    home = g["home"]["abbr"] == abbr
    return (g["home"], g["away"], True) if home else (g["away"], g["home"], False)


def result(g: dict, abbr: str) -> dict | None:
    """A final from this team's side: W, L or OT (lost in overtime or a shootout)."""
    us, them, home = _sides(g, abbr)
    if g.get("state") != "final" or us.get("score") is None or them.get("score") is None:
        return None
    won = us["score"] > them["score"]
    code = "T" if us["score"] == them["score"] else "W" if won else "OT" if g.get("outcome") in ("OT", "SO") else "L"
    return {"id": g["id"], "league": g.get("league", "nhl"), "date": g.get("date"), "opp": them["abbr"], "home": home,
            "us": us["score"], "them": them["score"], "code": code, "outcome": g.get("outcome"),
            "playoffs": g.get("type") == 3}


def record(results: list[dict]) -> str:
    w = sum(r["code"] == "W" for r in results)
    # College: W-L-T (a tie stands, overtime losses are losses). Pro: W-L-OT.
    if any(r["league"] in ("ncaam", "ncaaw") for r in results):
        return f"{w}-{sum(r['code'] in ('L', 'OT') for r in results)}-{sum(r['code'] == 'T' for r in results)}"
    return f"{w}-{sum(r['code'] == 'L' for r in results)}-{sum(r['code'] == 'OT' for r in results)}"


def streak(results: list[dict]) -> str | None:
    """Newest-first run of the same result: "W4", "L2", "OT1"."""
    if not results:
        return None
    last = results[-1]["code"]
    n = 0
    for r in reversed(results):
        if r["code"] != last:
            break
        n += 1
    return f"{last}{n}"


def race(row: dict, rows: list[dict]) -> str | None:
    """Points to the NHL playoff line in the team's conference: top 3 per division (wildcard 0) + 2 wildcards."""
    if not row.get("gp") or row.get("wildcard") is None:
        return None
    conf = [r for r in rows if r.get("conf") == row.get("conf") and r.get("wildcard") is not None]
    first_out = next((r for r in conf if r["wildcard"] == 3), None)
    last_in = next((r for r in conf if r["wildcard"] == 2), None)
    if row["wildcard"] <= 2 and first_out:
        gap = row["pts"] - first_out["pts"]
        return f"{gap} pt{'s' if gap != 1 else ''} above the playoff line" if gap > 0 else "On the playoff line"
    if last_in:
        gap = last_in["pts"] - row["pts"]
        return f"{gap} pt{'s' if gap != 1 else ''} out of a playoff spot" if gap > 0 else "Tied for the last playoff spot"
    return None


def standing(abbr: str, rows: list[dict], league: str) -> dict | None:
    row = next((r for r in rows if r.get("abbr") == abbr), None)
    if not row:
        return None
    if league == "pwhl":
        return {"place": f"{ordinal(row.get('league_rank'))} in the PWHL", "pts": row.get("pts"), "race": None}
    if league in ("ncaam", "ncaaw"):
        return {"place": f"No. {row['rank']} in the poll" if row.get("rank") else None, "pts": None, "race": None}
    return {"place": f"{ordinal(row.get('div_rank'))} in the {row.get('div')}", "pts": row.get("pts"),
            "race": race(row, rows)}


def team_summary(abbr: str, schedule: list[dict], rows: list[dict], today: str, league: str = "nhl") -> dict:
    """What the card shows for one team. `today` is the slate date (YYYY-MM-DD, Eastern)."""
    games = sorted(schedule, key=lambda g: (g.get("start") or g.get("date") or ""))
    results = [r for r in (result(g, abbr) for g in games) if r]
    # Only the latest season: walk back from the newest result until a summer-sized gap.
    for i in range(len(results) - 1, 0, -1):
        if _days(results[i - 1]["date"], results[i]["date"]) > BREAK:
            results = results[i:]
            break
    offseason = bool(results) and _days(results[-1]["date"], today) > BREAK
    week_from = (date.fromisoformat(today) - timedelta(days=WEEK)).isoformat()
    week = [r for r in results if (r["date"] or "") > week_from]
    ahead = [g for g in games if g.get("state") not in ("final", "postponed") and (g.get("date") or "") >= today]

    def brief(g: dict) -> dict:
        us, them, home = _sides(g, abbr)
        return {"id": g["id"], "league": g.get("league", league), "date": g.get("date"), "start": g.get("start"),
                "opp": them["abbr"], "home": home}

    place = standing(abbr, rows, league)
    if offseason:  # between seasons: last season's table and record, no streak or week
        week = []
        if place:
            place = {**place, "place": f"Last season {place['place']}", "race": None}
    return {
        "abbr": abbr, "league": league, "offseason": offseason,
        "next": ahead[0] if ahead else None,       # the full game (watch info included), for tonight or the next date
        "after": [brief(g) for g in ahead[1:4]],
        "last": results[-1] if results else None,
        "streak": None if offseason else streak(results), "record": record([r for r in results if not r["playoffs"]]) if results else None,  # regular season
        "week": {"record": record(week), "gf": sum(r["us"] for r in week), "ga": sum(r["them"] for r in week),
                 "games": len(week)} if week else None,
        "standing": place,
    }


# ---- milestone watch -------------------------------------------------------------------------------
# stat -> (round number step, how close counts, smallest target worth mentioning, who it applies to)
MILESTONES = {
    "goals": (50, 3, 50, "skater"), "assists": (100, 4, 100, "skater"), "points": (100, 4, 100, "skater"),
    "gp": (100, 3, 100, "all"), "wins": (50, 2, 50, "goalie"), "shutouts": (10, 1, 10, "goalie"),
}
WORDS = {"goals": ("goal", "goals"), "assists": ("assist", "assists"), "points": ("point", "points"),
         "gp": ("game", "games"), "wins": ("win", "wins"), "shutouts": ("shutout", "shutouts")}


def near_milestones(players: list[dict]) -> list[dict]:
    """Players within reach of a round career number, closest first."""
    out = []
    for p in players:
        for stat, (step, within, smallest, who) in MILESTONES.items():
            if who == "skater" and p.get("goalie") or who == "goalie" and not p.get("goalie"):
                continue
            now = p.get(stat) or 0
            target = (now // step + 1) * step
            left = target - now
            if target >= smallest and left <= within:
                one, many = WORDS[stat]
                out.append({"id": p.get("id"), "name": p["name"], "stat": stat, "now": now, "target": target, "left": left,
                            "text": f"{p['name']} is {left} {one if left == 1 else many} from {target:,}"})
    return sorted(out, key=lambda m: (m["left"] / MILESTONES[m["stat"]][1], -m["target"]))


def milestone_goal(career_goals: int, nth_tonight: int) -> int | None:
    """The round number a goal reaches, if it does: career total before tonight + this player's nth goal tonight."""
    total = career_goals + nth_tonight
    return total if total >= 50 and total % 50 == 0 else None
