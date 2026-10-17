"""NHL web API (api-web.nhle.com): fetching, and trimming responses down to what the app shows.

The API is undocumented. Every parser uses .get() with defaults so a missing field blanks one value
instead of breaking the page.
"""
from __future__ import annotations

from curl_cffi.requests import AsyncSession

from .odds import american

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


ODDS_PARTNER = "DraftKings"   # the US book in the scoreboard's oddsPartners list
ODDS_PARTNER_ID = 9           # its id there, used if the list is missing


def _odds(g: dict, partner: int) -> dict | None:
    """The partner's moneyline for both teams: {"away": -102, "home": -118}. The NHL drops odds once a game starts."""
    line = {}
    for side in ("away", "home"):
        v = next((o.get("value") for o in (g.get(f"{side}Team") or {}).get("odds") or [] if o.get("providerId") == partner), None)
        line[side] = american(v)
    return line if None not in line.values() else None


def parse_game(g: dict, odds_partner: int | None = None) -> dict:
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
        "odds": _odds(g, odds_partner) if odds_partner else None,
        "situation": parse_situation((g.get("situation") or {}).get("situationCode"),
                                     (g.get("awayTeam") or {}).get("abbrev") or "", (g.get("homeTeam") or {}).get("abbrev") or "",
                                     pd.get("periodType")) if state in ("LIVE", "CRIT") else None,
    }


def parse_score(data: dict) -> dict:
    """The /score/<date> day: every game with live score and clock, and the moneyline before puck drop."""
    partner = next((p.get("partnerId") for p in data.get("oddsPartners") or [] if p.get("name") == ODDS_PARTNER), ODDS_PARTNER_ID)
    return {"date": data.get("currentDate"), "prev": data.get("prevDate"), "next": data.get("nextDate"),
            "games": [parse_game(g, partner) for g in data.get("games") or []]}


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
                "scorer": _player_name(g), "pid": g.get("playerId"),
                "total": g.get("goalsToDate"),
                "assists": [{"name": _player_name(a), "pid": a.get("playerId"), "total": a.get("assistsToDate")}
                            for a in g.get("assists") or []],
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
        stars.append({"star": s.get("star"), "team": s.get("teamAbbrev"), "name": _player_name(s), "pid": s.get("playerId"),
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
        skaters = [{"number": p.get("sweaterNumber"), "name": _player_name(p), "pid": p.get("playerId"), "pos": p.get("position"),
                    "g": p.get("goals", 0), "a": p.get("assists", 0), "p": p.get("points", 0),
                    "pm": p.get("plusMinus", 0), "sog": p.get("sog", 0), "hits": p.get("hits", 0),
                    "toi": p.get("toi")} for p in (t.get("forwards") or []) + (t.get("defense") or [])]
        skaters.sort(key=lambda p: (-p["p"], -p["g"], -p["sog"]))
        goalies = [{"number": p.get("sweaterNumber"), "name": _player_name(p), "pid": p.get("playerId"), "sa": p.get("shotsAgainst", 0),
                    "saves": p.get("saves", 0), "ga": p.get("goalsAgainst", 0), "toi": p.get("toi"),
                    "starter": bool(p.get("starter"))}
                   for p in t.get("goalies") or [] if p.get("toi") not in (None, "00:00")]
        players[side] = {"skaters": skaters, "goalies": goalies}

    return {"game": game, "scoring": scoring, "penalties": penalties, "stars": stars, "linescore": linescore,
            "shots": shots, "team_stats": team_stats, "players": players,
            "preview": parse_preview(landing, rail) if game["state"] == "pre" else None}


RESULT = {"W": "W", "L": "L", "OTW": "W", "SOW": "W", "OTL": "OT", "SOL": "OT"}
PREVIEW_STATS = [  # (rail key, label, percent?, lower is better?)
    ("goalsForPerGamePlayed", "Goals for / game", False, False),
    ("goalsAgainstPerGamePlayed", "Goals against / game", False, True),
    ("ppPctg", "Power play", True, False),
    ("pkPctg", "Penalty kill", True, False),
    ("faceoffWinningPctg", "Faceoffs", True, False),
]
HOT_LABEL = {"points": "Points", "goals": "Goals", "assists": "Assists"}


def _hot(p: dict | None) -> dict | None:
    return {"name": _player_name(p), "number": p.get("sweaterNumber"), "pos": p.get("positionCode"),
            "value": p.get("value")} if p else None


def parse_preview(landing: dict, rail: dict | None) -> dict | None:
    """Before puck drop: form, season stats with league ranks, who's hot, goalies' season numbers, the season series,
    coaches and scratches. All from the landing + right-rail the game page loads anyway. The NHL doesn't name starting
    goalies here before the game."""
    m, rail = landing.get("matchup") or {}, rail or {}
    sides = ("away", "home")
    l10 = rail.get("last10Record") or {}
    form = {}
    for side in sides:
        t = l10.get(f"{side}Team") or {}
        st = {"W": "W", "L": "L", "OT": "OT", "O": "OT"}.get(t.get("streakType"))
        form[side] = {"record": t.get("record"), "streak": f"{st}{t.get('streak')}" if st and t.get("streak") else None,
                      "last": [{"opp": r.get("opponentAbbrev"), "res": RESULT.get(r.get("gameResult"), "L")}
                               for r in t.get("pastGameResults") or []]}  # newest first
    ts = rail.get("teamSeasonStats") or {}
    stats = []
    for key, label, pct, low in PREVIEW_STATS:
        a, h = (ts.get(f"{side}Team") or {} for side in sides)
        if a.get(key) is None or h.get(key) is None:
            continue
        fmt = (lambda v: f"{round(v * 100)}%") if pct else (lambda v: f"{v:.2f}")
        stats.append({"label": label, "away": fmt(a[key]), "home": fmt(h[key]), "low": low,
                      "away_rank": a.get(f"{key}Rank"), "home_rank": h.get(f"{key}Rank")})
    sc = m.get("skaterComparison") or {}
    hot = [{"label": HOT_LABEL.get(x.get("category"), (x.get("category") or "").title()),
            "away": _hot(x.get("awayLeader")), "home": _hot(x.get("homeLeader"))} for x in sc.get("leaders") or []]
    gc = m.get("goalieComparison") or {}
    goalies = {side: [{"name": _player_name(x), "number": x.get("sweaterNumber"), "gp": x.get("gamesPlayed") or 0,
                       "record": x.get("record"), "gaa": x.get("gaa"), "sv": x.get("savePctg"), "so": x.get("shutouts") or 0}
                      for x in sorted((gc.get(f"{side}Team") or {}).get("leaders") or [], key=lambda x: -(x.get("gamesPlayed") or 0))][:3]
               for side in sides}
    series = [{"id": x.get("id"), "date": x.get("gameDate"), "state": simple_state(x.get("gameState") or "FUT", x.get("gameScheduleState") or "OK"),
               "away": (x.get("awayTeam") or {}).get("abbrev"), "home": (x.get("homeTeam") or {}).get("abbrev"),
               "away_score": (x.get("awayTeam") or {}).get("score"), "home_score": (x.get("homeTeam") or {}).get("score"),
               "outcome": (x.get("gameOutcome") or {}).get("lastPeriodType")}
              for x in rail.get("seasonSeries") or [] if x.get("id") != landing.get("id")]
    wins = rail.get("seasonSeriesWins") or {}
    info = rail.get("gameInfo") or {}
    people = {side: {"coach": _t(((info.get(f"{side}Team") or {}).get("headCoach"))),
                     "scratches": [_player_name(x) for x in (info.get(f"{side}Team") or {}).get("scratches") or []]}
              for side in sides}
    out = {"form": form, "stats": stats, "hot": [h for h in hot if h["away"] or h["home"]], "goalies": goalies,
           "series": {"games": series, "away_wins": wins.get("awayTeamWins", 0), "home_wins": wins.get("homeTeamWins", 0)},
           "people": people, "hot_context": "last 5 games" if sc.get("contextLabel") == "last_5_games" else "this season"}
    return out if form["away"]["record"] or stats or hot else None


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


def parse_career(data: dict, player: dict) -> dict:
    """Career regular-season totals from player/<id>/landing, for milestone watch."""
    c = (data.get("careerTotals") or {}).get("regularSeason") or {}
    return {"id": player.get("id"), "name": player.get("name") or _player_name(data), "goalie": player.get("group") == "G",
            "goals": c.get("goals", 0), "assists": c.get("assists", 0), "points": c.get("points", 0),
            "gp": c.get("gamesPlayed", 0), "wins": c.get("wins", 0), "shutouts": c.get("shutouts", 0)}


def parse_club_stats(data: dict) -> dict:
    skaters = [{"name": _player_name(p), "pid": p.get("playerId"), "pos": p.get("positionCode"), "gp": p.get("gamesPlayed", 0),
                "g": p.get("goals", 0), "a": p.get("assists", 0), "p": p.get("points", 0),
                "pm": p.get("plusMinus", 0)} for p in data.get("skaters") or []]
    skaters.sort(key=lambda p: (-p["p"], -p["g"]))
    goalies = [{"name": _player_name(p), "pid": p.get("playerId"), "gp": p.get("gamesPlayed", 0), "w": p.get("wins", 0),
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


# ---- players ------------------------------------------------------------------------------------
def season_label(season) -> str:
    """20262027 -> "2026-27"."""
    s = str(season or "")
    return f"{s[:4]}-{s[6:]}" if len(s) == 8 else s


def current_season(today: str) -> str:
    """The season id for a date: a new season's photos and numbers start in July."""
    y, m = int(today[:4]), int(today[5:7])
    return f"{y}{y + 1}" if m >= 7 else f"{y - 1}{y}"


def _feet(inches) -> str | None:
    return f"{inches // 12}'{inches % 12}\"" if isinstance(inches, int) and inches else None


def _skater_line(x: dict) -> dict:
    return {"gp": x.get("gamesPlayed", 0), "g": x.get("goals", 0), "a": x.get("assists", 0), "p": x.get("points", 0),
            "pm": x.get("plusMinus", 0), "pim": x.get("pim", 0), "shots": x.get("shots", 0),
            "ppg": x.get("powerPlayGoals", 0), "toi": x.get("avgToi")}


def _goalie_line(x: dict) -> dict:
    return {"gp": x.get("gamesPlayed", 0), "w": x.get("wins", 0), "l": x.get("losses", 0), "otl": x.get("otLosses", 0),
            "gaa": round(x.get("goalsAgainstAvg") or 0, 2), "svpct": round(x.get("savePctg") or 0, 3),
            "so": x.get("shutouts", 0)}


def parse_player(landing: dict) -> dict:
    """player/<id>/landing: who they are, this season, career, season by season."""
    goalie = landing.get("position") == "G"
    line = _goalie_line if goalie else _skater_line
    place = ", ".join(x for x in (_t(landing.get("birthCity")), _t(landing.get("birthStateProvince")),
                                  landing.get("birthCountry")) if x)
    d = landing.get("draftDetails") or {}
    draft = (f"{d['year']} · Round {d.get('round')} · #{d.get('overallPick')} overall ({d.get('teamAbbrev')})"
             if d.get("year") else None)
    awards = [{"name": _t(a.get("trophy")), "seasons": [season_label(s.get("seasonId")) for s in a.get("seasons") or []]}
              for a in landing.get("awards") or []]
    feat = (landing.get("featuredStats") or {}).get("regularSeason") or {}
    career = landing.get("careerTotals") or {}
    rows = [r for r in landing.get("seasonTotals") or [] if r.get("gameTypeId") == 2]
    seasons = [{"season": season_label(r.get("season")), "league": r.get("leagueAbbrev"), "team": _t(r.get("teamName")),
                **line(r)} for r in reversed(rows)]
    cur = (landing.get("featuredStats") or {}).get("season")
    now = [r for r in rows if r.get("season") == cur and r.get("leagueAbbrev") == "NHL"]
    season = {"label": season_label(cur), **line(feat["subSeason"])} if feat.get("subSeason") and cur else None
    if season and not goalie and len(now) == 1:   # traded mid-season: two rows, and no one average for both
        season["toi"] = now[0].get("avgToi")
    return {
        "league": "nhl", "id": landing.get("playerId"), "name": _player_name(landing),
        "number": landing.get("sweaterNumber"), "pos": landing.get("position"), "goalie": goalie,
        "team": landing.get("currentTeamAbbrev") if landing.get("isActive") else None,
        "active": bool(landing.get("isActive")),
        "facts": {"born": landing.get("birthDate"), "birthplace": place or None, "country": landing.get("birthCountry"),
                  "height": _feet(landing.get("heightInInches")), "weight": landing.get("weightInPounds"),
                  "shoots": landing.get("shootsCatches")},
        "draft": draft, "awards": awards,
        "season": season,
        "career": {"regular": line(career["regularSeason"]) if career.get("regularSeason") else None,
                   "playoffs": line(career["playoffs"]) if career.get("playoffs") else None},
        "seasons": seasons,
    }


def parse_game_log(data: dict, goalie: bool) -> list[dict]:
    """player/<id>/game-log/now, newest first."""
    out = []
    for x in data.get("gameLog") or []:
        row = {"date": x.get("gameDate"), "game": x.get("gameId"), "opp": x.get("opponentAbbrev"),
               "home": x.get("homeRoadFlag") == "H", "toi": x.get("toi")}
        if goalie:
            row.update(dec=x.get("decision"), sa=x.get("shotsAgainst", 0), ga=x.get("goalsAgainst", 0),
                       svpct=round(x.get("savePctg") or 0, 3))
        else:
            row.update(g=x.get("goals", 0), a=x.get("assists", 0), p=x.get("points", 0), pm=x.get("plusMinus", 0),
                       shots=x.get("shots", 0))
        out.append(row)
    return out


LEADER_CATS = {"points": "Points", "goals": "Goals", "assists": "Assists",
               "wins": "Wins", "savePctg": "Save %", "goalsAgainstAverage": "GAA"}


def parse_leaders(skaters: dict, goalies: dict) -> dict:
    """skater-stats-leaders + goalie-stats-leaders: {category: [{pid, name, team, pos, value}]}."""
    out = {}
    for src in (skaters or {}, goalies or {}):
        for cat, rows in src.items():
            if cat not in LEADER_CATS or not isinstance(rows, list):
                continue
            out[cat] = [{"pid": r.get("id"), "name": _player_name(r), "team": r.get("teamAbbrev"),
                         "pos": r.get("position"), "value": r.get("value")} for r in rows]
    return out
