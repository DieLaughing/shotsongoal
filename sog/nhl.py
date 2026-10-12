"""NHL web API (api-web.nhle.com): fetching, and trimming responses down to what the app shows.

The API is undocumented. Every parser uses .get() with defaults so a missing field blanks one value
instead of breaking the page.
"""
from __future__ import annotations

from curl_cffi.requests import AsyncSession

BASE = "https://api-web.nhle.com/v1"
_session: AsyncSession | None = None


async def get(path: str) -> dict:
    # A browser fingerprint: the API answers Python's default client with 403.
    global _session
    if _session is None:
        _session = AsyncSession(impersonate="chrome", timeout=20)
    r = await _session.get(f"{BASE}/{path.lstrip('/')}", allow_redirects=True)
    r.raise_for_status()
    return r.json()


def _t(v) -> str:
    """Localised name objects look like {"default": "Bruins", "fr": ...}."""
    if isinstance(v, dict):
        return v.get("default") or ""
    return v or ""


ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}


def period_label(pd: dict | None, game_type: int = 2) -> str:
    pd = pd or {}
    n, kind = pd.get("number") or 0, pd.get("periodType") or "REG"
    if kind == "SO":
        return "SO"
    if kind == "OT":
        ot = n - (pd.get("maxRegulationPeriods") or 3)
        return "OT" if ot <= 1 else f"{ot}OT"
    return ORDINAL.get(n, f"{n}th")


def simple_state(state: str, sched: str = "OK") -> str:
    if sched in ("PPD", "SUSP", "CNCL"):
        return "postponed"
    return {"LIVE": "live", "CRIT": "live", "FINAL": "final", "OFF": "final"}.get(state, "pre")


def _team(t: dict) -> dict:
    return {
        "abbr": t.get("abbrev") or "",
        "name": _t(t.get("commonName") or t.get("name")),
        "place": _t(t.get("placeName")),
        "score": t.get("score"),
        "sog": t.get("sog"),
    }


def parse_situation(code: str | None, away: str, home: str, period_type: str | None = None) -> dict | None:
    """situationCode = away goalie, away skaters, home skaters, home goalie, in that order: "1451" = away goalie in, 4 away
    skaters, 5 home skaters, home goalie in (home power play). A pulled goalie adds an extra skater."""
    if not code or len(code) != 4 or not code.isdigit():
        return None
    ag, ask, hsk, hg = (int(c) for c in code)
    notes = []
    if ag == 0:
        notes.append(f"{away} goalie pulled")
    if hg == 0:
        notes.append(f"{home} goalie pulled")
    a_eff, h_eff = ask - (1 if ag == 0 else 0), hsk - (1 if hg == 0 else 0)
    pp = away if a_eff > h_eff else home if h_eff > a_eff else None
    if pp:
        notes.insert(0, f"{pp} power play ({max(a_eff, h_eff)} on {min(a_eff, h_eff)})")
    elif a_eff < 5 and period_type == "REG":
        notes.insert(0, f"{a_eff} on {h_eff}")
    if not notes:
        return None
    return {"code": code, "power_play": pp, "away_pulled": ag == 0, "home_pulled": hg == 0, "text": " · ".join(notes)}


def _score_goals(g: dict) -> list[dict]:
    """Goals as the scoreboard lists them: enough for alerts and the Tonight cards."""
    out = []
    for x in g.get("goals") or []:
        pd = x.get("periodDescriptor") or {"number": x.get("period")}
        out.append({"key": f"{pd.get('number')}-{x.get('timeInPeriod')}-{x.get('playerId')}",
                    "period": period_label(pd, g.get("gameType") or 2), "time": x.get("timeInPeriod"),
                    "team": _t(x.get("teamAbbrev")), "scorer": _player_name(x), "total": x.get("goalsToDate"),
                    "strength": (x.get("strength") or "ev").upper(),
                    "empty_net": x.get("goalModifier") == "empty-net",
                    "away": x.get("awayScore"), "home": x.get("homeScore")})
    return out


def parse_game(g: dict) -> dict:
    clock = g.get("clock") or {}
    pd = g.get("periodDescriptor") or {}
    state = g.get("gameState") or "FUT"
    sched = g.get("gameScheduleState") or "OK"
    recap = g.get("threeMinRecap")
    return {
        "id": g.get("id"),
        "date": g.get("gameDate"),
        "start": g.get("startTimeUTC"),
        "type": g.get("gameType"),
        "state": simple_state(state, sched),
        "raw_state": state,
        "away": _team(g.get("awayTeam") or {}),
        "home": _team(g.get("homeTeam") or {}),
        "period": period_label(pd, g.get("gameType") or 2) if pd.get("number") else None,
        "clock": clock.get("timeRemaining"),
        "running": bool(clock.get("running")),
        "intermission": bool(clock.get("inIntermission")),
        "outcome": (g.get("gameOutcome") or {}).get("lastPeriodType"),
        "venue": _t(g.get("venue")),
        "recap": f"https://www.nhl.com{recap}" if recap else None,
        "tickets": g.get("ticketsLink") or None,  # Ticketmaster, from the NHL's own schedule
        "broadcasts": [{"network": (b.get("network") or "").strip(), "market": b.get("market"),
                        "country": b.get("countryCode")} for b in g.get("tvBroadcasts") or []],
        "goals": _score_goals(g),
        "situation": parse_situation((g.get("situation") or {}).get("situationCode"),
                                     (g.get("awayTeam") or {}).get("abbrev") or "", (g.get("homeTeam") or {}).get("abbrev") or "",
                                     pd.get("periodType")) if state in ("LIVE", "CRIT") else None,
    }


def parse_score(data: dict) -> dict:
    """The /score/<date> day: every game with live score and clock."""
    return {"date": data.get("currentDate"), "prev": data.get("prevDate"), "next": data.get("nextDate"),
            "games": [parse_game(g) for g in data.get("games") or []]}


def _player_name(p: dict | None) -> str:
    if not p:
        return ""
    if p.get("name"):
        return _t(p["name"])
    return f"{_t(p.get('firstName'))} {_t(p.get('lastName'))}".strip()


def _desc(key: str | None) -> str:
    return (key or "").replace("-", " ").capitalize()


def parse_detail(landing: dict, rail: dict | None, box: dict | None) -> dict:
    """One game's page: summary, scoring, penalties, stars, team stats and player stats."""
    game = parse_game(landing)
    gtype = landing.get("gameType") or 2
    summary = landing.get("summary") or {}

    scoring = []
    for per in summary.get("scoring") or []:
        goals = []
        for g in per.get("goals") or []:
            goals.append({
                "time": g.get("timeInPeriod"),
                "team": _t(g.get("teamAbbrev")),
                "scorer": _player_name(g),
                "total": g.get("goalsToDate"),
                "assists": [{"name": _player_name(a), "total": a.get("assistsToDate")} for a in g.get("assists") or []],
                "strength": (g.get("strength") or "ev").upper(),
                "modifier": g.get("goalModifier") if g.get("goalModifier") not in (None, "none") else None,
                "away": g.get("awayScore"), "home": g.get("homeScore"),
                "clip": g.get("highlightClipSharingUrl"),
            })
        scoring.append({"period": period_label(per.get("periodDescriptor"), gtype), "goals": goals})

    penalties = []
    for per in summary.get("penalties") or []:
        items = []
        for p in per.get("penalties") or []:
            who = p.get("committedByPlayer") or p.get("servedBy")
            items.append({
                "time": p.get("timeInPeriod"),
                "team": _t(p.get("teamAbbrev")),
                "player": _player_name(who) if isinstance(who, dict) else _t(who),
                "minutes": p.get("duration"),
                "kind": p.get("type"),
                "desc": _desc(p.get("descKey")),
            })
        penalties.append({"period": period_label(per.get("periodDescriptor"), gtype), "items": items})

    stars = []
    for s in summary.get("threeStars") or []:
        if "savePctg" in s:
            line = f"{s.get('savePctg', 0):.3f} SV%".lstrip("0")
        else:
            line = f"{s.get('goals', 0)}G {s.get('assists', 0)}A"
        stars.append({"star": s.get("star"), "team": s.get("teamAbbrev"), "name": _player_name(s),
                      "pos": s.get("position"), "line": line})

    rail = rail or {}
    linescore = [{"period": period_label(p.get("periodDescriptor"), gtype), "away": p.get("away"), "home": p.get("home")}
                 for p in (rail.get("linescore") or {}).get("byPeriod") or []]
    shots = [{"period": period_label(p.get("periodDescriptor"), gtype), "away": p.get("away"), "home": p.get("home")}
             for p in rail.get("shotsByPeriod") or []]
    labels = {"sog": "Shots", "faceoffWinningPctg": "Faceoffs", "powerPlay": "Power play", "pim": "Penalty minutes",
              "hits": "Hits", "blockedShots": "Blocked shots", "giveaways": "Giveaways", "takeaways": "Takeaways"}
    team_stats = []
    for s in rail.get("teamGameStats") or []:
        cat = s.get("category")
        if cat not in labels:
            continue
        a, h = s.get("awayValue"), s.get("homeValue")
        if cat == "faceoffWinningPctg":
            a, h = f"{round((a or 0) * 100)}%", f"{round((h or 0) * 100)}%"
        team_stats.append({"label": labels[cat], "away": a, "home": h})

    players = {}
    for side in ("away", "home"):
        t = ((box or {}).get("playerByGameStats") or {}).get(f"{side}Team") or {}
        skaters = [{"number": p.get("sweaterNumber"), "name": _player_name(p), "pos": p.get("position"),
                    "g": p.get("goals", 0), "a": p.get("assists", 0), "p": p.get("points", 0),
                    "pm": p.get("plusMinus", 0), "sog": p.get("sog", 0), "hits": p.get("hits", 0),
                    "toi": p.get("toi")} for p in (t.get("forwards") or []) + (t.get("defense") or [])]
        skaters.sort(key=lambda p: (-p["p"], -p["g"], -p["sog"]))
        goalies = [{"number": p.get("sweaterNumber"), "name": _player_name(p), "sa": p.get("shotsAgainst", 0),
                    "saves": p.get("saves", 0), "ga": p.get("goalsAgainst", 0), "toi": p.get("toi"),
                    "starter": bool(p.get("starter"))}
                   for p in t.get("goalies") or [] if p.get("toi") not in (None, "00:00")]
        players[side] = {"skaters": skaters, "goalies": goalies}

    return {"game": game, "scoring": scoring, "penalties": penalties, "stars": stars, "linescore": linescore,
            "shots": shots, "team_stats": team_stats, "players": players}


def parse_standings(data: dict) -> list[dict]:
    rows = []
    for s in data.get("standings") or []:
        rows.append({
            "abbr": _t(s.get("teamAbbrev")), "name": _t(s.get("teamName")), "short": _t(s.get("teamCommonName")),
            "conf": s.get("conferenceName"), "div": s.get("divisionName"),
            "gp": s.get("gamesPlayed", 0), "w": s.get("wins", 0), "l": s.get("losses", 0), "otl": s.get("otLosses", 0),
            "pts": s.get("points", 0), "rw": s.get("regulationWins", 0), "gd": s.get("goalDifferential", 0),
            "gf": s.get("goalFor", 0), "ga": s.get("goalAgainst", 0), "pct": s.get("pointPctg", 0),
            "l10": f"{s.get('l10Wins', 0)}-{s.get('l10Losses', 0)}-{s.get('l10OtLosses', 0)}",
            "streak": f"{s.get('streakCode') or ''}{s.get('streakCount') or ''}",
            "div_rank": s.get("divisionSequence"), "conf_rank": s.get("conferenceSequence"),
            "league_rank": s.get("leagueSequence"), "wildcard": s.get("wildcardSequence"),
        })
    return rows


def parse_club_schedule(data: dict) -> list[dict]:
    return [parse_game(g) for g in data.get("games") or []]


def parse_roster(data: dict) -> list[dict]:
    out = []
    for group, label in (("forwards", "F"), ("defensemen", "D"), ("goalies", "G")):
        for p in data.get(group) or []:
            out.append({"id": p.get("id"), "number": p.get("sweaterNumber"), "name": _player_name(p),
                        "pos": p.get("positionCode"), "group": label, "shoots": p.get("shootsCatches"),
                        "born": p.get("birthDate"), "height": p.get("heightInInches"),
                        "country": p.get("birthCountry")})
    return out


def parse_club_stats(data: dict) -> dict:
    skaters = [{"name": _player_name(p), "pos": p.get("positionCode"), "gp": p.get("gamesPlayed", 0),
                "g": p.get("goals", 0), "a": p.get("assists", 0), "p": p.get("points", 0),
                "pm": p.get("plusMinus", 0)} for p in data.get("skaters") or []]
    skaters.sort(key=lambda p: (-p["p"], -p["g"]))
    goalies = [{"name": _player_name(p), "gp": p.get("gamesPlayed", 0), "w": p.get("wins", 0),
                "l": p.get("losses", 0), "otl": p.get("overtimeLosses", 0),
                "gaa": round(p.get("goalsAgainstAverage") or 0, 2), "svpct": round(p.get("savePercentage") or 0, 3)}
               for p in data.get("goalies") or []]
    goalies.sort(key=lambda p: -p["gp"])
    return {"skaters": skaters, "goalies": goalies}


SHOT_TYPES = {"goal": "goal", "shot-on-goal": "shot", "missed-shot": "miss"}


def parse_pbp(data: dict) -> dict:
    """Shot locations for the shot map, plus the current on-ice situation.

    Rink coordinates run x -100..100 (end boards), y -42.5..42.5. Teams switch ends each period; every shot is
    turned so the home team always shoots to the right and the away team to the left.
    """
    away = (data.get("awayTeam") or {})
    home = (data.get("homeTeam") or {})
    home_id = home.get("id")
    names = {p.get("playerId"): _player_name(p) for p in data.get("rosterSpots") or []}
    shots = []
    for p in data.get("plays") or []:
        kind = SHOT_TYPES.get(p.get("typeDescKey"))
        d = p.get("details") or {}
        if not kind or d.get("xCoord") is None or d.get("yCoord") is None:
            continue
        x, y = d["xCoord"], d["yCoord"]
        is_home = d.get("eventOwnerTeamId") == home_id
        # Make every shot head towards the net it attacked, then put home shots on the right.
        attacking_right = (p.get("homeTeamDefendingSide") == "left") == is_home
        if not attacking_right:
            x, y = -x, -y
        if not is_home:
            x, y = -x, -y
        shooter = d.get("scoringPlayerId") or d.get("shootingPlayerId")
        shots.append({"x": x, "y": y, "team": home.get("abbrev") if is_home else away.get("abbrev"),
                      "kind": kind, "period": period_label(p.get("periodDescriptor")), "time": p.get("timeInPeriod"),
                      "shooter": names.get(shooter, ""), "shot_type": d.get("shotType")})
    last = next((p for p in reversed(data.get("plays") or []) if p.get("situationCode")), None)
    situation = None
    if last and data.get("gameState") in ("LIVE", "CRIT"):
        situation = parse_situation(last["situationCode"], away.get("abbrev") or "", home.get("abbrev") or "",
                                    (last.get("periodDescriptor") or {}).get("periodType"))
    return {"shots": shots, "situation": situation}


def recap(detail: dict) -> str | None:
    """A few plain sentences for a finished game, built from its scoring and stats."""
    g = detail["game"]
    if g["state"] != "final" or g["away"]["score"] is None:
        return None
    a, h = g["away"], g["home"]
    win, lose = (a, h) if a["score"] > h["score"] else (h, a)
    how = {"OT": " in overtime", "SO": " in a shootout"}.get(g.get("outcome") or "", "")
    where = "at home" if win is h else "on the road"
    parts = [f"The {win['name'] or win['abbr']} beat the {lose['name'] or lose['abbr']} "
             f"{win['score']}-{lose['score']}{how} {where}."]
    # Game-winner: the winning team's goal that put them one ahead of the loser's final total.
    goals = [{**x, "period": per["period"]} for per in detail.get("scoring") or [] for x in per["goals"]]
    side = "away" if win is a else "home"
    gwg = next((x for x in goals if x["team"] == win["abbr"] and x[side] == lose["score"] + 1), None)
    if gwg and g.get("outcome") != "SO":
        when = "in overtime" if gwg["period"].endswith("OT") else f"at {gwg['time']} of the {gwg['period']}"
        parts.append(f"{gwg['scorer']} scored the winner {when}.")
    multi = {}
    for x in goals:
        multi[x["scorer"]] = multi.get(x["scorer"], 0) + 1
    hat = [n for n, c in multi.items() if c >= 3]
    if hat:
        parts.append(f"{hat[0]} had a hat trick.")
    if detail.get("stars"):
        s1 = detail["stars"][0]
        parts.append(f"First star: {s1['name']} ({s1['line']}).")
    if a.get("sog") is not None and h.get("sog") is not None:
        more, fewer = (a, h) if a["sog"] >= h["sog"] else (h, a)
        if more["sog"] != fewer["sog"]:
            parts.append(f"{more.get('code') or more['abbr']} outshot {fewer.get('code') or fewer['abbr']} {more['sog']}-{fewer['sog']}.")
    return " ".join(parts)
