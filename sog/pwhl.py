"""PWHL data from HockeyTech (LeagueStat), the platform behind thepwhl.com's own stats pages.

The key and client code are the public ones the league's site loads inline. Responses are trimmed into the same
shapes as sog/nhl.py, so the web app draws both leagues with one set of views. PWHL team keys carry a "PW-"
prefix (PW-BOS) because codes like BOS, MTL, SEA and VAN exist in both leagues.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from curl_cffi.requests import AsyncSession

from .nhl import ORDINAL

FEED = "https://lscluster.hockeytech.com/feed/index.php"
PARAMS = {"key": "446521baf8c38984", "client_code": "pwhl", "fmt": "json", "lang": "en"}
WHERE_TO_WATCH = "https://www.thepwhl.com/en/where-to-watch"
TICKETS = "https://www.thepwhl.com/en/tickets"  # until the feed fills in each game's TicketUrl
PREFIX = "PW-"
_session: AsyncSession | None = None


async def get(**params) -> dict:
    global _session
    if _session is None:
        _session = AsyncSession(impersonate="chrome", timeout=25)
    r = await _session.get(FEED, params={**PARAMS, **params})
    r.raise_for_status()
    text = r.text.strip()
    return json.loads(text[1:-1] if text.startswith("(") else text)  # some views answer as JSONP "(...)"


def key(code: str) -> str:
    return f"{PREFIX}{code}" if code else ""


def _int(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def period_label(short: str | None) -> str | None:
    """'1' -> 1st, 'OT1' -> OT, 'OT2' -> 2OT, 'SO' -> SO."""
    s = (short or "").upper()
    if not s:
        return None
    if s == "SO":
        return "SO"
    if s.startswith("OT"):
        n = _int(s[2:], 1)
        return "OT" if n <= 1 else f"{n}OT"
    return ORDINAL.get(_int(s), f"{s}th")


def _utc(iso: str | None) -> str | None:
    try:
        return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


# ---- seasons -------------------------------------------------------------------------------
def parse_seasons(data: dict) -> list[dict]:
    out = []
    for s in (data.get("SiteKit") or {}).get("Seasons") or []:
        name = s.get("season_name") or ""
        kind = 3 if "Playoff" in name else 1 if "Pre" in name else 2
        out.append({"id": str(s.get("season_id")), "name": name, "type": kind,
                    "start": s.get("start_date"), "end": s.get("end_date")})
    return out


def current_season(seasons: list[dict], today: str, kind: int = 2) -> dict | None:
    """The season of `kind` running today, else the next one, else the latest."""
    of_kind = sorted((s for s in seasons if s["type"] == kind), key=lambda s: s["start"] or "")
    for s in of_kind:
        if (s["start"] or "") <= today <= (s["end"] or ""):
            return s
    upcoming = [s for s in of_kind if (s["start"] or "") > today]
    return upcoming[0] if upcoming else (of_kind[-1] if of_kind else None)


# ---- games -----------------------------------------------------------------------------------
def _side(g: dict, side: str) -> dict:
    code = g.get(f"{side}Code") or ""
    nick = g.get(f"{side}Nickname") or ""
    city = g.get(f"{side}City") or ""
    return {"abbr": key(code), "code": code, "name": city if nick in ("", "PWHL") else nick, "place": city,
            "score": _int(g.get(f"{side}Goals"), None), "sog": None}


def parse_game(g: dict, season_types: dict[str, int] | None = None) -> dict:
    status = str(g.get("GameStatus") or "1")
    text = g.get("GameStatusString") or ""
    short = g.get("PeriodNameShort") or g.get("Period")
    state = ("postponed" if "postpon" in text.lower() else "final" if status == "4"
             else "pre" if status == "1" else "live")
    outcome = None
    if state == "final":
        s = (short or "").upper()
        outcome = "SO" if s == "SO" else "OT" if s.startswith("OT") else "REG"
    away, home = _side(g, "Visitor"), _side(g, "Home")
    if state == "pre":
        away["score"] = home["score"] = None
    return {
        "id": _int(g.get("ID")), "league": "pwhl", "date": g.get("Date"), "start": _utc(g.get("GameDateISO8601")),
        "type": (season_types or {}).get(str(g.get("SeasonID")), 2),
        "state": state, "raw_state": status, "away": away, "home": home,
        "period": period_label(short) if state == "live" else None,
        "clock": g.get("GameClock") if state == "live" else None, "running": state == "live",
        "intermission": str(g.get("Intermission")) == "1", "outcome": outcome,
        "venue": (g.get("venue_name") or "").split(" | ")[0], "recap": None,
        "tickets": g.get("TicketUrl") or (TICKETS if state == "pre" else None),
        "broadcasts": [], "goals": [], "situation": None,
    }


def parse_scorebar(data: dict, season_types: dict[str, int] | None = None) -> list[dict]:
    return [parse_game(g, season_types) for g in (data.get("SiteKit") or {}).get("Scorebar") or []]


def day(games: list[dict], date: str) -> dict:
    """One date's slate in the shape of nhl.parse_score, with the nearest dates that have games."""
    dates = sorted({g["date"] for g in games if g.get("date")})
    prev = max((d for d in dates if d < date), default=None)
    nxt = min((d for d in dates if d > date), default=None)
    return {"date": date, "prev": prev, "next": nxt, "games": [g for g in games if g.get("date") == date]}


# ---- one game ----------------------------------------------------------------------------------
def _name(p: dict | None) -> str:
    return f"{(p or {}).get('first_name', '')} {(p or {}).get('last_name', '')}".strip()


def _short(p: dict | None) -> str:
    first, last = (p or {}).get("first_name", ""), (p or {}).get("last_name", "")
    return f"{first[:1]}. {last}".strip(". ") if first else last


def parse_detail(summary: dict, pxp: dict | None, base: dict | None) -> dict:
    """Summary + play-by-play into nhl.parse_detail's shape. `base` is the game as the scorebar has it."""
    g = (summary.get("GC") or {}).get("Gamesummary") or {}
    home_id, away_id = str((g.get("home") or {}).get("id")), str((g.get("visitor") or {}).get("id"))
    code_of = {home_id: (g.get("home") or {}).get("code", ""), away_id: (g.get("visitor") or {}).get("code", "")}
    game = dict(base or {})
    shots = g.get("totalShots") or {}
    if game:
        game["away"] = {**game["away"], "sog": _int(shots.get("visitor"), None)}
        game["home"] = {**game["home"], "sog": _int(shots.get("home"), None)}
    periods = {str(k): v.get("long_name") for k, v in (g.get("periods") or {}).items()}

    def plabel(pid) -> str:
        p = str(pid)
        return {"4": "OT", "5": "SO"}.get(p, periods.get(p) or ORDINAL.get(_int(p), p)) if _int(p) <= 5 else f"{_int(p) - 3}OT"

    scoring: dict[str, list] = {}
    a = h = 0
    for x in g.get("goals") or []:
        home = str(x.get("home")) == "1"
        a, h = (a, h + 1) if home else (a + 1, h)
        assists = [p for p in (x.get("assist1_player"), x.get("assist2_player")) if p and p.get("first_name")]
        strength = "PP" if x.get("power_play") == "1" else "SH" if x.get("short_handed") == "1" else "EV"
        scoring.setdefault(plabel(x.get("period_id")), []).append({
            "time": x.get("time"), "team": key(code_of.get(str(x.get("team_id")), "")),
            "scorer": _short(x.get("goal_scorer")), "pid": _int((x.get("goal_scorer") or {}).get("player_id"), None),
            "total": _int(x.get("scorer_goal_num"), None),
            "assists": [{"name": _short(p), "pid": _int(p.get("player_id"), None), "total": None} for p in assists],
            "strength": strength,
            "modifier": "empty-net" if x.get("empty_net") == "1" else None, "away": a, "home": h, "clip": None})
    penalties: dict[str, list] = {}
    for x in g.get("penalties") or []:
        who = x.get("player_served_info") or x.get("player_penalized_info")
        penalties.setdefault(plabel(x.get("period_id")), []).append({
            "time": x.get("time_off_formatted"), "team": key(code_of.get(str(x.get("team_id")), "")),
            "player": _name(who) if who else "Bench", "minutes": _int(x.get("minutes")),
            "kind": x.get("penalty_class"), "desc": x.get("lang_penalty_description") or ""})

    lineup = {"home": g.get("home_team_lineup") or {}, "away": g.get("visitor_team_lineup") or {}}
    by_id = {}
    for side, lu in lineup.items():
        for p in (lu.get("players") or []) + (lu.get("goalies") or []):
            by_id[str(p.get("player_id"))] = (side, p)
    stars = []
    for i, m in enumerate(g.get("mvps") or [], 1):
        side, p = by_id.get(str(m.get("player_id")), ("home" if str(m.get("home")) == "1" else "away", {}))
        team = key(code_of.get(home_id if side == "home" else away_id, ""))
        if p.get("position_str") == "G" or "saves" in p:
            sa, sv = _int(p.get("shots_against")), _int(p.get("saves"))
            line = f"{sv / sa:.3f} SV%".lstrip("0") if sa else "Goalie"
        else:
            line = f"{_int(p.get('goals'))}G {_int(p.get('assists'))}A"
        stars.append({"star": i, "team": team, "name": _short(m), "pid": _int(m.get("player_id"), None),
                      "pos": p.get("position_str"), "line": line})

    gbp, sbp = g.get("goalsByPeriod") or {}, g.get("shotsByPeriod") or {}
    keys = sorted(set((gbp.get("home") or {}) | (gbp.get("visitor") or {})), key=_int)
    linescore = [{"period": plabel(k), "away": _int((gbp.get("visitor") or {}).get(k)), "home": _int((gbp.get("home") or {}).get(k))}
                 for k in keys]
    shots_by = [{"period": plabel(k), "away": _int((sbp.get("visitor") or {}).get(k)), "home": _int((sbp.get("home") or {}).get(k))}
                for k in sorted(set((sbp.get("home") or {}) | (sbp.get("visitor") or {})), key=_int)]
    fo, hits, pim, ppg = (g.get(k) or {} for k in ("totalFaceoffs", "totalHits", "pimTotal", "powerPlayGoals"))

    def fo_pct(side):
        f = fo.get(side) or {}
        return f"{round(100 * _int(f.get('won')) / _int(f.get('att'), 1))}%" if _int(f.get("att")) else "–"
    team_stats = [{"label": "Shots", "away": _int(shots.get("visitor")), "home": _int(shots.get("home"))},
                  {"label": "Faceoffs", "away": fo_pct("visitor"), "home": fo_pct("home")},
                  {"label": "Power-play goals", "away": _int(ppg.get("visitor")), "home": _int(ppg.get("home"))},
                  {"label": "Penalty minutes", "away": _int(pim.get("visitor")), "home": _int(pim.get("home"))},
                  {"label": "Hits", "away": _int(hits.get("visitor")), "home": _int(hits.get("home"))}]

    players = {}
    for side, lu in lineup.items():
        skaters = [{"number": p.get("jersey_number"), "name": _short(p), "pid": _int(p.get("player_id"), None), "pos": p.get("position_str"),
                    "g": _int(p.get("goals")), "a": _int(p.get("assists")), "p": _int(p.get("goals")) + _int(p.get("assists")),
                    "pm": _int(p.get("plusminus")), "sog": _int(p.get("shots_on")), "hits": _int(p.get("hits")), "toi": None}
                   for p in lu.get("players") or []]
        skaters.sort(key=lambda p: (-p["p"], -p["g"], -p["sog"]))
        goalies = [{"number": p.get("jersey_number"), "name": _short(p), "pid": _int(p.get("player_id"), None), "sa": _int(p.get("shots_against")),
                    "saves": _int(p.get("saves")), "ga": _int(p.get("goals_against")),
                    "toi": f"{_int(p.get('seconds')) // 60}:{_int(p.get('seconds')) % 60:02d}", "starter": p.get("start") == "1"}
                   for p in lu.get("goalies") or [] if _int(p.get("seconds"))]
        players[side] = {"skaters": skaters, "goalies": goalies}

    scoring_list = [{"period": k, "goals": v} for k, v in scoring.items()]
    detail = {"game": game, "scoring": scoring_list, "penalties": [{"period": k, "items": v} for k, v in penalties.items()],
              "stars": stars, "linescore": linescore, "shots": shots_by, "team_stats": team_stats, "players": players,
              "shotmap": parse_shots(pxp, code_of, {pid: _short(p) for pid, (_, p) in by_id.items()}), "situation": None}
    return detail


def parse_shots(pxp: dict | None, code_of: dict[str, str], names: dict[str, str]) -> list[dict]:
    """HockeyTech draws a 600x300 rink with the away team attacking right. Turn it so the home team shoots
    right, in NHL rink units (x -100..100, y -42.5..42.5), like the NHL shot map."""
    out = []
    events = ((pxp or {}).get("GC") or {}).get("Pxpverbose") or []
    for e in events:
        if e.get("event") not in ("shot", "goal") or e.get("x_location") in (None, "") or e.get("y_location") in (None, ""):
            continue
        x, y = _int(e["x_location"]), _int(e["y_location"])
        team = str(e.get("team_id"))
        shooter = str(e.get("player_id") or e.get("goal_player_id") or "")
        out.append({"x": round(100 - x / 3, 1), "y": round(42.5 - y * 85 / 300, 1), "team": key(code_of.get(team, "")),
                    "kind": "goal" if e["event"] == "goal" else "shot", "period": period_label(str(e.get("period_id"))) or "",
                    "time": e.get("time") or e.get("time_formatted"),
                    "shooter": _short(e.get("goal_scorer")) if e.get("goal_scorer") else names.get(shooter, ""),
                    "shot_type": None})
    return out


# ---- standings, teams --------------------------------------------------------------------------------
def parse_standings(data) -> list[dict]:
    rows = data if isinstance(data, list) else ((data.get("SiteKit") or {}).get("Statviewtype") or [])
    out = []
    for s in rows:
        if not s.get("team_code"):
            continue  # header rows ("repeatheader")
        name = (s.get("name") or "").split(" - ", 1)[-1]  # "x - Montréal Victoire": drop the clinch marker
        out.append({
            "abbr": key(s["team_code"]), "code": s["team_code"], "name": name,
            "short": s.get("nickname") if s.get("nickname") not in (None, "", "PWHL") else s.get("city"),
            "conf": None, "div": s.get("division_name") if s.get("division_name") not in (None, "", "PWHL") else None,
            "gp": _int(s.get("games_played")), "w": _int(s.get("regulation_wins")), "otw": _int(s.get("non_reg_wins")),
            "otl": _int(s.get("non_reg_losses")), "l": _int(s.get("losses")), "pts": _int(s.get("points")),
            "rw": _int(s.get("regulation_wins")), "gd": _int(s.get("goals_for")) - _int(s.get("goals_against")),
            "gf": _int(s.get("goals_for")), "ga": _int(s.get("goals_against")),
            "l10": s.get("past_10") or "", "streak": s.get("streak") or "", "league_rank": _int(s.get("overall_rank") or s.get("rank"), 99),
            "clinched": s.get("clinched") or "",
        })
    out.sort(key=lambda r: r["league_rank"])
    return out


def parse_roster(data) -> list[dict]:
    rows = data if isinstance(data, list) else ((data.get("SiteKit") or {}).get("Roster") or [])
    flat = []
    for r in rows:  # the roster mixes player rows with nested lists (staff sections)
        flat += r if isinstance(r, list) else [r]
    rows = [r for r in flat if isinstance(r, dict)]
    group = {"F": "F", "C": "F", "LW": "F", "RW": "F", "D": "D", "LD": "D", "RD": "D", "G": "G"}
    out = []
    for p in rows:
        pos = (p.get("position") or "").upper()
        if not p.get("last_name") or pos not in group:
            continue  # coaches and staff are on the same list
        out.append({"id": _int(p.get("player_id") or p.get("id"), None), "number": _int(p.get("tp_jersey_number"), None),
                    "name": _name(p), "pos": pos, "group": group[pos], "shoots": p.get("shoots"),
                    "born": p.get("birthdate") or p.get("rawbirthdate"), "height": None,
                    "country": p.get("birthcntry") or p.get("homecntry")})
    return out


def parse_scorers(skaters, goalies) -> dict:
    sk = [{"name": p.get("name"), "pid": _int(p.get("player_id"), None), "team": key(p.get("team_code") or ""),
           "pos": p.get("position"), "gp": _int(p.get("games_played")), "g": _int(p.get("goals")),
           "a": _int(p.get("assists")), "p": _int(p.get("points")), "pm": _int(p.get("plus_minus"))} for p in skaters or []]
    sk.sort(key=lambda p: (-p["p"], -p["g"]))
    gl = [{"name": p.get("name"), "pid": _int(p.get("player_id"), None), "team": key(p.get("team_code") or ""),
           "gp": _int(p.get("games_played")), "w": _int(p.get("wins")), "l": _int(p.get("losses")),
           "otl": _int(p.get("ot_losses")), "gaa": float(p.get("goals_against_average") or 0),
           "svpct": float(p.get("save_percentage") or 0)} for p in goalies or []]
    gl.sort(key=lambda p: -p["gp"])
    return {"skaters": sk, "goalies": gl}


# ---- players ------------------------------------------------------------------------------------
POS = {"F": "F", "C": "C", "LW": "L", "RW": "R", "D": "D", "LD": "D", "RD": "D", "G": "G"}
COUNTRY = {"United States": "USA", "Canada": "CAN", "Sweden": "SWE", "Finland": "FIN", "Czechia": "CZE",
           "Czech Republic": "CZE", "Switzerland": "SUI", "Germany": "GER", "Japan": "JPN", "Austria": "AUT",
           "Hungary": "HUN", "Denmark": "DEN", "France": "FRA", "Norway": "NOR", "Slovakia": "SVK"}


def _season_short(name: str) -> str:
    """"2025-26 Regular Season" -> "2025-26"; "2024 Regular Season" -> "2024"."""
    return (name or "").replace(" Regular Season", "").strip()


def _sk(x: dict) -> dict:
    return {"gp": _int(x.get("games_played")), "g": _int(x.get("goals")), "a": _int(x.get("assists")),
            "p": _int(x.get("points")), "pm": _int(x.get("plus_minus")), "pim": _int(x.get("penalty_minutes")),
            "shots": _int(x.get("shots")), "ppg": _int(x.get("power_play_goals")), "toi": None}


def _gk(x: dict) -> dict:
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    return {"gp": _int(x.get("games_played")), "w": _int(x.get("wins")), "l": _int(x.get("losses")),
            "otl": _int(x.get("ot_losses")) + _int(x.get("shootout_losses")),
            "gaa": round(num(x.get("goals_against_average") or x.get("gaa")), 2),
            "svpct": round(num(x.get("savepct")), 3), "so": _int(x.get("shutouts"))}


def parse_player(profile: dict, stats: dict, log: dict, pid: int) -> dict:
    """HockeyTech's player profile, seasonstats and gamebygame, in nhl.parse_player's shape (plus the game log)."""
    p = ((profile or {}).get("SiteKit") or {}).get("Player") or {}
    pos = (p.get("position") or "").upper()
    goalie = pos == "G"
    line = _gk if goalie else _sk
    regular = (((stats or {}).get("SiteKit") or {}).get("Player") or {}).get("regular") or []
    rows = [r for r in regular if r.get("season_name") != "Total" and r.get("career") != "0"]
    total = next((r for r in regular if r.get("season_name") == "Total"), None)
    playoff = (((stats or {}).get("SiteKit") or {}).get("Player") or {}).get("playoff") or []
    ptotal = next((r for r in playoff if r.get("season_name") == "Total"), None)
    seasons = [{"season": _season_short(r.get("season_name")), "league": "PWHL", "team": r.get("team_name"), **line(r)}
               for r in rows]
    games = (((log or {}).get("SiteKit") or {}).get("Player") or {}).get("games") or []
    out_log = []
    for g in reversed(games):
        home = str(g.get("home")) == "1"
        row = {"date": g.get("date_played"), "game": _int(g.get("id"), None),
               "opp": key(g.get("visiting_team_code") if home else g.get("home_team_code")), "home": home}
        if goalie:
            sa, ga = _int(g.get("shots_against")), _int(g.get("goals_against"))
            row.update(dec="W" if g.get("win") == "1" else "OT" if _int(g.get("ot_loss")) or _int(g.get("shootout_loss"))
                       else "L" if g.get("loss") == "1" else None, sa=sa, ga=ga,
                       svpct=round((sa - ga) / sa, 3) if sa else 0, toi=g.get("minutes"))
        else:
            row.update(g=_int(g.get("goals")), a=_int(g.get("assists")), p=_int(g.get("points")),
                       pm=_int(g.get("plus_minus") or g.get("plusminus")), shots=_int(g.get("shots")),
                       toi=g.get("ice_time_minutes_seconds"))
        out_log.append(row)
    country = p.get("birthcntry") or ""
    born = p.get("birthdate") if (p.get("birthdate") or "")[:4].isdigit() else None
    return {
        "league": "pwhl", "id": pid, "name": p.get("name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
        "number": _int(p.get("jersey_number"), None), "pos": POS.get(pos, pos), "goalie": goalie,
        "team": key(p.get("most_recent_team_code") or "") or None, "active": p.get("active") == "1",
        "facts": {"born": born, "country": COUNTRY.get(country, country[:3].upper() or None),
                  "birthplace": ", ".join(x for x in (p.get("birthtown"), p.get("birthprov"), country) if x) or None,
                  "height": p.get("height") or None, "weight": _int(p.get("weight"), None) or None,
                  "shoots": p.get("catches" if goalie else "shoots") or None},
        "draft": None, "awards": [],
        "season": {"label": seasons[0]["season"], **{k: v for k, v in seasons[0].items() if k not in ("season", "league", "team")}} if seasons else None,
        "career": {"regular": line(total) if total else None, "playoffs": line(ptotal) if ptotal else None},
        "seasons": seasons, "log": out_log,
    }


def parse_leaders(scorers: dict, goalies: dict) -> dict:
    """League-wide topscorers + topgoalies, in nhl.parse_leaders' shape."""
    sk = ((scorers or {}).get("SiteKit") or {}).get("Statviewtype") or []
    gl = ((goalies or {}).get("SiteKit") or {}).get("Statviewtype") or []

    def row(p, value):
        return {"pid": _int(p.get("player_id"), None), "name": p.get("name"), "team": key(p.get("team_code") or ""),
                "pos": POS.get((p.get("position") or "").upper(), p.get("position")), "value": value}
    sk = [p for p in sk if p.get("player_id")]
    gl = [p for p in gl if p.get("player_id") and _int(p.get("games_played"))]
    out = {cat: [row(p, _int(p.get(field))) for p in sorted(sk, key=lambda p: (-_int(p.get(field)), -_int(p.get("points"))))]
           for cat, field in (("points", "points"), ("goals", "goals"), ("assists", "assists"))}
    most = max((_int(p.get("games_played")) for p in gl), default=0)
    qualified = [p for p in gl if _int(p.get("games_played")) >= most / 3]   # a few starts can't top save %
    out["wins"] = [row(p, _int(p.get("wins"))) for p in sorted(gl, key=lambda p: -_int(p.get("wins")))]
    out["savePctg"] = [row(p, float(p.get("save_percentage") or 0)) for p in sorted(qualified, key=lambda p: -float(p.get("save_percentage") or 0))]
    out["goalsAgainstAverage"] = [row(p, float(p.get("goals_against_average") or 0))
                                  for p in sorted(qualified, key=lambda p: float(p.get("goals_against_average") or 99))]
    return out


def name_changes(data: dict, ours: dict[str, tuple[str, str, str]]) -> list[dict]:
    """Teams whose name in the league's feed no longer matches ours (teams.PWHL), or that we don't know at all.
    An expansion team's feed nickname is "PWHL" until it's announced; that isn't a change."""
    out = []
    for t in (data.get("SiteKit") or {}).get("Teamsbyseason") or []:
        code, nick = t.get("code") or "", (t.get("nickname") or "").strip()
        k = key(code)
        if k not in ours:
            out.append({"key": k, "code": code, "feed": t.get("name") or code, "ours": None})
        elif nick and nick != "PWHL" and nick != ours[k][1]:
            out.append({"key": k, "code": code, "feed": nick, "ours": ours[k][1], "full": t.get("name")})
    return out
