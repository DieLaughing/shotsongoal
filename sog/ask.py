"""Ask (prototype): a question in plain words -> an answer card, drawn on the phone by OpenUI (openui.com).

The model never writes the answer. A small local model (llama.cpp's server, SOG_LLM_URL) only fills in a form: what
kind of question it is and which names it mentions. The names are then looked up in the teams list and the rosters,
the numbers come from the copies the app already keeps, and this module writes the OpenUI Lang page itself. A name
nobody plays under gets "couldn't find", never a made-up player or stat. Questions that are just names ("Bruins",
"Pastrnak vs Marner") skip the model entirely.
"""
from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import re
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo

from curl_cffi.requests import AsyncSession

from . import home, spoilers, teams

LLM_URL = os.environ.get("SOG_LLM_URL", "").rstrip("/")
LLM_TIMEOUT = 20        # s; the 4B model on 4 VPS cores answers in ~2-3 s
MAX_QUESTION = 200      # characters
PLANS_KEPT = 500        # questions remembered (same words -> same plan, no model call)
ET = ZoneInfo("America/New_York")
log = logging.getLogger("sog.ask")

KINDS = ("about", "leaders", "standings", "games", "other")
STATS = {"points": "points", "goals": "goals", "assists": "assists", "wins": "wins", "save_pct": "savePctg", "gaa": "goalsAgainstAverage"}
GROUPS = {"league": None, "eastern": "Eastern", "western": "Western", "atlantic": "Atlantic", "metropolitan": "Metropolitan",
          "central": "Central", "pacific": "Pacific"}
DAYS = ("yesterday", "today", "tomorrow")

# The form the model fills in. Leaving fields out keeps the answer short: generating is the slow part on a CPU.
SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"enum": list(KINDS)},
        "names": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
        "stat": {"enum": list(STATS)},
        "group": {"enum": list(GROUPS)},
        "day": {"enum": list(DAYS)},
    },
    "required": ["kind"],
}
SYSTEM = """You fill in a form for a hockey app. Never answer the question; only describe it.
kind: "about" = the question is about one or two named teams or players (stats, form, how they're doing, comparing them, head to head); "leaders" = who leads the league in a stat; "standings" = the table of teams or who is first; "games" = which games are on, or the scores, for a day; "other" = anything else.
names: team or player names copied from the question as written (nicknames are fine), at most 2.
stat: what "leaders" ranks. group: which table "standings" shows. day: which day "games" means (last night = yesterday). Leave out fields that don't apply."""
EXAMPLES = [
    ("How are the Bruins doing?", {"kind": "about", "names": ["Bruins"]}),
    ("pasta vs marner", {"kind": "about", "names": ["pasta", "marner"]}),
    ("who has the most goals", {"kind": "leaders", "stat": "goals"}),
    ("scores last night?", {"kind": "games", "day": "yesterday"}),
]
TRY = ["How are the Bruins doing?", "Kings vs Ducks", "Who leads the league in goals?", "Atlantic standings", "Games tonight"]


# ---- names -------------------------------------------------------------------------------------
def norm(s: str) -> str:
    """Lowercase, no accents or punctuation: "Montréal", "B's" and "Stützle" match how people type them."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]+", "", s.replace("-", " ")).split())


# What fans call teams beyond city and nickname. A city two teams share (New York) isn't a name.
ALIASES = {"habs": "MTL", "leafs": "TOR", "bs": "BOS", "pens": "PIT", "caps": "WSH", "bolts": "TBL", "avs": "COL",
           "canes": "CAR", "sens": "OTT", "preds": "NSH", "nucks": "VAN", "isles": "NYI", "hawks": "CHI", "jackets": "CBJ",
           "knights": "VGK", "wings": "DET", "la": "LAK", "tampa": "TBL", "jersey": "NJD", "philly": "PHI", "stl": "STL"}


def _team_names() -> dict[str, str]:
    out, cities = {}, {}
    for abbr, (city, nick, _) in teams.TEAMS.items():
        cities.setdefault(norm(city), []).append(abbr)
        for k in (abbr, nick, f"{city} {nick}", nick.rstrip("s") if nick.endswith("s") else None):
            if k:
                out[norm(k)] = abbr
    out.update({c: a[0] for c, a in cities.items() if len(a) == 1})
    out.update(ALIASES)
    return out


TEAM_NAMES = _team_names()
FILLER = re.compile(r"^(the|how are|how is|hows|how s|tell me about|show me|what about) |( this (year|season)| doing| lately)$")


def find_team(name: str) -> str | None:
    n = norm(name)
    while (m := FILLER.sub("", n)) != n:
        n = m.strip()
    if n in TEAM_NAMES:
        return TEAM_NAMES[n]
    close = difflib.get_close_matches(n, TEAM_NAMES, n=1, cutoff=0.85)
    return TEAM_NAMES[close[0]] if close else None


def find_players(name: str, index: list[list]) -> list[list]:
    """NHL players ([id, name, team, pos]) a name could mean, best first: the full name, a unique last (or first)
    name, then a near spelling. More than one = ask which."""
    n = norm(name)
    if len(n) < 3:
        return []
    rows = [r for r in index if not str(r[2]).startswith("PW-")]
    full = [r for r in rows if norm(r[1]) == n]
    if full:
        return full
    parts = [r for r in rows if n in (norm(r[1]).split()[-1], norm(r[1]).split()[0], " ".join(norm(r[1]).split()[1:]))]
    if parts:
        return parts[:5]
    names = {norm(r[1]): r for r in rows}
    lasts = {}
    for r in rows:
        lasts.setdefault(norm(r[1]).split()[-1], []).append(r)
    close = difflib.get_close_matches(n, names, n=3, cutoff=0.8)
    if close:
        return [names[c] for c in close]
    close = difflib.get_close_matches(n, lasts, n=1, cutoff=0.8)
    return lasts[close[0]][:5] if close else []


# ---- the question -> a plan ---------------------------------------------------------------------------
_plans: dict[str, dict] = {}
_session: AsyncSession | None = None
_one_at_a_time = asyncio.Lock()   # the server runs one slot; queueing here keeps the timeout honest


def quick(q: str, index: list[list]) -> dict | None:
    """A question that is only names ("Bruins", "kings vs ducks", "Pastrnak and Marchand") needs no model."""
    parts = [p for p in re.split(r"\s+(?:vs\.?|v\.?|versus|and|or|&)\s+|\s*,\s*", norm(q.replace("?", ""))) if p]
    if not 1 <= len(parts) <= 2:
        return None
    if all(find_team(p) for p in parts) or all(not find_team(p) and len(find_players(p, index)) == 1 for p in parts):
        return {"kind": "about", "names": parts}
    return None


def clean(plan: dict) -> dict:
    """Whatever the model sent, as a plan with only known values."""
    kind = plan.get("kind") if plan.get("kind") in KINDS else "other"
    names = [str(x)[:60] for x in plan.get("names") or [] if isinstance(x, str) and x.strip()][:2]
    return {"kind": kind, "names": names, "stat": plan.get("stat") if plan.get("stat") in STATS else None,
            "group": plan.get("group") if plan.get("group") in GROUPS else None,
            "day": plan.get("day") if plan.get("day") in DAYS else None}


async def understand(q: str, index: list[list]) -> dict:
    key = norm(q)
    if key in _plans:
        return _plans[key]
    plan = quick(q, index)
    if plan is None:
        if not LLM_URL:
            raise RuntimeError("no model configured (SOG_LLM_URL)")
        plan = await _ask_model(q)
    plan = clean(plan)
    if len(_plans) >= PLANS_KEPT:
        _plans.clear()
    _plans[key] = plan
    return plan


async def _ask_model(q: str) -> dict:
    global _session
    if _session is None:
        _session = AsyncSession(timeout=LLM_TIMEOUT)
    msgs = [{"role": "system", "content": SYSTEM}]
    for asked, plan in EXAMPLES:
        msgs += [{"role": "user", "content": asked}, {"role": "assistant", "content": json.dumps(plan)}]
    msgs.append({"role": "user", "content": q})
    body = {"messages": msgs, "temperature": 0, "max_tokens": 60, "cache_prompt": True,
            "response_format": {"type": "json_schema", "json_schema": {"schema": SCHEMA}}}
    async with _one_at_a_time:
        r = await _session.post(f"{LLM_URL}/v1/chat/completions", json=body)
    r.raise_for_status()
    out = r.json()
    t = out.get("timings") or {}
    log.info("ask: model %.0f ms (%s prompt, %s out)", (t.get("prompt_ms") or 0) + (t.get("predicted_ms") or 0),
             t.get("prompt_n"), t.get("predicted_n"))
    return json.loads(out["choices"][0]["message"]["content"])


# ---- OpenUI Lang ---------------------------------------------------------------------------------
class Raw(str):
    """Already OpenUI Lang (a component call or an action), written as is."""


def lit(x) -> str:
    if isinstance(x, Raw):
        return x
    if x is None:
        return "null"
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, (int, float, str)):
        return json.dumps(x, ensure_ascii=False)
    if isinstance(x, (list, tuple)):
        return "[" + ", ".join(lit(i) for i in x) + "]"
    if isinstance(x, dict):
        return "{" + ", ".join(f"{k}: {lit(i)}" for k, i in x.items()) + "}"
    raise TypeError(type(x))


def c(name: str, *args) -> Raw:
    """A component call; trailing missing (None) arguments are left off."""
    args = list(args)
    while args and args[-1] is None:
        args.pop()
    return Raw(f"{name}({', '.join(lit(a) for a in args)})")


def go(href: str) -> Raw:
    return Raw(f"@OpenUrl({lit(href)})")


class Page:
    """One answer: a Card whose parts are written as their own statements after `root`, so the outline draws first."""

    def __init__(self):
        self.parts: list[str] = []

    def add(self, *blocks: Raw | None) -> Page:
        self.parts += [b for b in blocks if b]
        return self

    def text(self) -> str:
        names = [f"b{i}" for i in range(len(self.parts))]
        return "\n".join([f"root = Card([{', '.join(names)}])", *(f"{n} = {p}" for n, p in zip(names, self.parts))])


def follow(*qs: str) -> Raw:
    return c("FollowUpBlock", [c("FollowUpItem", q) for q in qs if q])


def metric(label: str, value, sub: str | None = None) -> Raw:
    return c("SnippetCardItem", None, c("IconText", c("Icon", ICONS.get(label, "hash")), "soft", "s", label),
             c("BoldText", "number", str(value), sub))


def numbers(*items: Raw) -> Raw:
    """Headline numbers, two to a row."""
    return c("SnippetCardBlock", list(items), "grid", False)


ICONS = {"Points": "trophy", "Goal diff": "scale", "Last 10": "history", "League": "list-ordered", "Goals": "target",
         "Assists": "handshake", "+/-": "plus-minus", "Games": "calendar", "Wins": "trophy", "GAA": "shield", "Save %": "shield-check"}


def full(abbr: str) -> str:
    city, nick, _ = teams.TEAMS.get(abbr, (abbr, "", ""))
    return f"{city} {nick}".strip()


def nick(abbr: str) -> str:
    return teams.TEAMS.get(abbr, ("", abbr, ""))[1]


def day_label(d: str | None) -> str:
    try:
        return date.fromisoformat(d).strftime("%a %b %-d")
    except (TypeError, ValueError):
        return d or ""


def clock(start: str | None) -> str:
    try:
        return datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(ET).strftime("%-I:%M %p ET").lower().replace(" et", " ET")
    except (AttributeError, ValueError):
        return ""


def pct(x) -> str:
    return f"{x:.3f}".lstrip("0") if isinstance(x, (int, float)) else "–"


# ---- answers ---------------------------------------------------------------------------------------
def unsure(title: str, text: str, *tries: str) -> str:
    return Page().add(c("TextCallout", "neutral", title, text), follow(*(tries or TRY[:3]))).text()


def spoiler_wall(what: str) -> str:
    return Page().add(c("TextCallout", "warning", "Spoiler-free is on",
                        f"{what} would give away a game you're hiding. Watch it (or mark it seen) first."),
                      c("Buttons", [c("Button", "Tonight's games", go("#/"), "secondary")])).text()


def team_page(abbr: str, rows: list[dict], schedule: list[dict], skaters: list[dict]) -> str:
    st = next((r for r in rows if r["abbr"] == abbr), None)
    p = Page()
    sub = " · ".join(x for x in (f"{home.ordinal(st['div_rank'])} in the {st['div']}" if st and st.get("div_rank") else "",
                                 f"{st['w']}-{st['l']}-{st['otl']}" if st else "",
                                 f"Streak {st['streak']}" if st and st.get("streak") else "") if x)
    p.add(c("CardHeader", full(abbr), sub or "This season"))
    if st:
        p.add(numbers(*[metric("Points", st["pts"], f"in {st['gp']} games"),
                                      metric("Goal diff", f"{st['gd']:+d}", f"{st['gf']} for, {st['ga']} against"),
                                      metric("Last 10", st["l10"]), metric("League", home.ordinal(st.get("league_rank")) or "–")]))
    done = [r for r in (home.result(g, abbr) for g in schedule) if r][-5:]
    if done:
        p.add(c("InlineHeader", "Last games"),
              c("ListBlock", [c("ListItem", f"{r['code']} {r['us']}-{r['them']} {'vs' if r['home'] else 'at'} {nick(r['opp'])}"
                                + (" (SO)" if r.get("outcome") == "SO" else ""),
                                day_label(r["date"]), None, "Game", go(f"#/game/{r['id']}")) for r in reversed(done)], None, "small"))
    nxt = next((g for g in schedule if g.get("state") == "pre"), None)
    if nxt:
        us_home = nxt["home"]["abbr"] == abbr
        other = nxt["away" if us_home else "home"]["abbr"]
        p.add(c("TextContent", f"**Next:** {'vs' if us_home else 'at'} {full(other)}, {day_label(nxt['date'])} at {clock(nxt.get('start'))}"))
    top = sorted(skaters, key=lambda x: (-x["p"], -x["g"]))[:5]
    if top and top[0]["p"]:
        p.add(c("InlineHeader", "Top scorers", "Points this season"),
              c("HorizontalBarChart", [x["name"] for x in top], [c("Series", "Points", [x["p"] for x in top])]))
    p.add(c("Buttons", [c("Button", "Team page", go(f"#/team/{abbr}"), "secondary")]))
    rival = next((r["abbr"] for r in rows if st and r["div"] == st["div"] and r["abbr"] != abbr), None)
    return p.add(follow(f"{nick(abbr)} vs {nick(rival)}" if rival else "", top[0]["name"] if top else "",
                        f"{st['div']} standings" if st else "")).text()


TEAM_STATS = [("Points", "pts"), ("Wins", "w"), ("Goals for", "gf"), ("Goals against", "ga"), ("Goal diff", "gd")]


def teams_page(a: str, b: str, rows: list[dict], schedule_a: list[dict]) -> str:
    ra, rb = (next((r for r in rows if r["abbr"] == x), None) for x in (a, b))
    p = Page().add(c("CardHeader", f"{nick(a)} vs {nick(b)}", "This season"))
    if ra and rb:
        p.add(c("Table", [c("Col", "", [n for n, _ in TEAM_STATS] + ["Record", "Last 10"]),
                          c("Col", a, [ra[k] for _, k in TEAM_STATS] + [f"{ra['w']}-{ra['l']}-{ra['otl']}", ra["l10"]]),
                          c("Col", b, [rb[k] for _, k in TEAM_STATS] + [f"{rb['w']}-{rb['l']}-{rb['otl']}", rb["l10"]])]),
              c("BarChart", ["Points", "Goals for", "Goals against"],
                [c("Series", nick(x), [r["pts"], r["gf"], r["ga"]]) for x, r in ((a, ra), (b, rb))]))
    meet = [g for g in schedule_a if {g["away"]["abbr"], g["home"]["abbr"]} == {a, b} and g.get("type") in (2, 3)]
    played = [r for r in (home.result(g, a) for g in meet) if r]
    if played:
        won = sum(r["code"] == "W" for r in played)
        p.add(c("InlineHeader", "Head to head", f"{nick(a)} {won}-{len(played) - won} this season"),
              c("ListBlock", [c("ListItem", f"{nick(a)} {r['us']}-{r['them']} {nick(b)}", day_label(r["date"]), None, "Game",
                                go(f"#/game/{r['id']}")) for r in played], None, "small"))
    nxt = next((g for g in meet if g.get("state") == "pre"), None)
    if nxt:
        p.add(c("TextContent", f"**Next meeting:** {day_label(nxt['date'])} at {clock(nxt.get('start'))}, in {teams.TEAMS[nxt['home']['abbr']][0]}"))
    return p.add(follow(full(a), full(b))).text()


def _who(pl: dict) -> str:
    return " · ".join(str(x) for x in (f"#{pl['number']}" if pl.get("number") else "", pl.get("pos"),
                                         full(pl["team"]) if pl.get("team") else "") if x)


def player_page(pl: dict, hide: set[int]) -> str:
    s = pl.get("season") or {}
    log_ = [g for g in pl.get("log") or [] if g.get("game") not in hide]
    p = Page().add(c("CardHeader", pl["name"], f"{_who(pl)} · {s.get('label', 'This season')}"))
    if pl.get("goalie"):
        p.add(numbers(metric("Games", s.get("gp", 0)), metric("Wins", s.get("w", 0)),
                      metric("GAA", s.get("gaa", "–")), metric("Save %", pct(s.get("svpct")))))
        recent = list(reversed(log_[:12]))
        if len(recent) >= 2:
            p.add(c("InlineHeader", "Shots, game by game", f"Last {len(recent)} games"),
                  c("BarChart", [g["opp"] for g in recent], [c("Series", "Saves", [g["sa"] - g["ga"] for g in recent]),
                                                            c("Series", "Goals against", [g["ga"] for g in recent])], "stacked"))
        rows = log_[:5]
        if rows:
            p.add(c("Table", [c("Col", "Date", [day_label(g["date"]) for g in rows]), c("Col", "Opp", [g["opp"] for g in rows]),
                              c("Col", "Dec", [g.get("dec") or "–" for g in rows]), c("Col", "SA", [g["sa"] for g in rows], "number"),
                              c("Col", "Sv%", [pct(g["svpct"]) for g in rows])]))
    else:
        p.add(numbers(metric("Goals", s.get("g", 0), f"{s.get('gp', 0)} games"), metric("Assists", s.get("a", 0)),
                      metric("Points", s.get("p", 0)), metric("+/-", f"{s.get('pm', 0):+d}")))
        recent = list(reversed(log_[:12]))
        if len(recent) >= 2:
            p.add(c("InlineHeader", "Points, game by game", f"Last {len(recent)} games"),
                  c("BarChart", [g["opp"] for g in recent], [c("Series", "Goals", [g["g"] for g in recent]),
                                                            c("Series", "Assists", [g["a"] for g in recent])], "stacked"))
        rows = log_[:5]
        if rows:
            p.add(c("Table", [c("Col", "Date", [day_label(g["date"]) for g in rows]), c("Col", "Opp", [g["opp"] for g in rows]),
                              c("Col", "G", [g["g"] for g in rows], "number"), c("Col", "A", [g["a"] for g in rows], "number"),
                              c("Col", "Shots", [g["shots"] for g in rows], "number")]))
    p.add(c("Buttons", [c("Button", "Player page", go(f"#/player/{pl['id']}"), "secondary")]))
    return p.add(follow(full(pl["team"]) if pl.get("team") else "", "Who leads the league in points?")).text()


SKATER_CMP = [("Games", "gp"), ("Goals", "g"), ("Assists", "a"), ("Points", "p"), ("+/-", "pm"), ("Shots", "shots"), ("PP goals", "ppg")]
GOALIE_CMP = [("Games", "gp"), ("Wins", "w"), ("Losses", "l"), ("GAA", "gaa"), ("Save %", "svpct"), ("Shutouts", "so")]


def players_page(a: dict, b: dict) -> str:
    sa, sb = a.get("season") or {}, b.get("season") or {}
    stats = GOALIE_CMP if a.get("goalie") and b.get("goalie") else SKATER_CMP if not a.get("goalie") and not b.get("goalie") else [("Games", "gp")]
    show = lambda s, k: pct(s.get(k)) if k == "svpct" else s.get(k, 0)
    p = Page().add(c("CardHeader", f"{a['name']} vs {b['name']}", sa.get("label") or "This season"),
                   c("Table", [c("Col", "", [n for n, _ in stats]), c("Col", a["name"].split()[-1], [show(sa, k) for _, k in stats]),
                               c("Col", b["name"].split()[-1], [show(sb, k) for _, k in stats])]))
    if stats is SKATER_CMP:
        p.add(c("BarChart", ["Goals", "Assists", "Points"],
                [c("Series", x["name"].split()[-1], [s.get("g", 0), s.get("a", 0), s.get("p", 0)]) for x, s in ((a, sa), (b, sb))]))
    elif stats is not GOALIE_CMP:
        p.add(c("TextContent", "One skater and one goalie: their seasons don't compare stat for stat."))
    p.add(c("Buttons", [c("Button", x["name"], go(f"#/player/{x['id']}"), "secondary") for x in (a, b)]))
    return p.add(follow(a["name"], b["name"])).text()


def leaders_page(stat: str, data: dict) -> str:
    cat = STATS[stat]
    rows = (data.get("cats") or {}).get(cat) or []
    rows = rows[:10]
    label = {"savePctg": "Save %", "goalsAgainstAverage": "Goals against average"}.get(cat, cat.capitalize())
    if not rows:
        return unsure("No leaders yet", "The league hasn't published leaders for this season yet.")
    vals = [round(r["value"], 3) if isinstance(r["value"], float) else r["value"] for r in rows]
    p = Page().add(c("CardHeader", f"{label} leaders", data.get("season") or "This season"),
                   c("HorizontalBarChart", [f"{r['name']} ({r['team']})" for r in rows], [c("Series", label, vals)]),
                   c("ListBlock", [c("ListItem", r["name"], f"{full(r['team'])} · {pct(v) if cat == 'savePctg' else v}", None, "Player",
                                     go(f"#/player/{r['pid']}")) for r, v in zip(rows[:5], vals)], "number", "small"))
    others = [s for s in ("points", "goals", "assists", "wins", "save_pct") if s != stat][:3]
    return p.add(follow(*(f"Who leads in {s.replace('_', ' ')}?" for s in others))).text()


def standings_page(group: str | None, rows: list[dict]) -> str:
    want = GROUPS.get(group or "league")
    rows = [r for r in rows if not want or want in (r.get("conf"), r.get("div"))]
    if not rows:
        return unsure("No standings yet", "The league hasn't published standings yet.")
    rows = sorted(rows, key=lambda r: (-r["pts"], r["gp"], -r["rw"]))
    title = f"{want} {'Conference' if want in ('Eastern', 'Western') else 'Division'}" if want else "League standings"
    cols = [("Team", [nick(r["abbr"]) for r in rows], None), ("GP", [r["gp"] for r in rows], "number"),
            ("W", [r["w"] for r in rows], "number"), ("L", [r["l"] for r in rows], "number"),
            ("OT", [r["otl"] for r in rows], "number"), ("PTS", [r["pts"] for r in rows], "number"),
            ("GD", [f"{r['gd']:+d}" for r in rows], None)]
    p = Page().add(c("CardHeader", title, f"{len(rows)} teams, most points first"),
                   c("Table", [c("Col", n, d, t) for n, d, t in cols]),
                   c("Buttons", [c("Button", "League tab", go("#/league"), "secondary")]))
    return p.add(follow(full(rows[0]["abbr"]), "Western standings" if want != "Western" else "Eastern standings")).text()


def games_page(slate: dict, which: str, sp: dict | None, today: str) -> str:
    games = slate.get("games") or []
    title = {"yesterday": "Last night", "tomorrow": "Tomorrow", "today": "Tonight"}[which]
    if not games:
        return unsure(f"{title}: no games", "No NHL games on that day.", "Games tomorrow", "Who won last night?")

    def line(g):
        a, h = g["away"], g["home"]
        if g.get("state") in ("live", "final") and not spoilers.hidden(dict(g, league="nhl"), sp, today):
            score = f"{a['abbr']} {a.get('score')} - {h.get('score')} {h['abbr']}"
            if g["state"] == "final":
                return score, "Final" + (f" ({g['outcome']})" if g.get("outcome") in ("OT", "SO") else "")
            return score, " · ".join(x for x in ("Live", g.get("period"), g.get("clock")) if x)
        if g.get("state") in ("live", "final"):
            return f"{nick(a['abbr'])} at {nick(h['abbr'])}", "Hidden (spoiler-free)"
        return f"{nick(a['abbr'])} at {nick(h['abbr'])}", clock(g.get("start"))
    items = [c("ListItem", *line(g), None, "Game", go(f"#/game/{g['id']}")) for g in games]
    return Page().add(c("CardHeader", title, f"{day_label(slate.get('date'))} · {len(games)} games"),
                      c("ListBlock", items, None, "small"),
                      follow(*(f"Games {d}" for d in DAYS if d != which))).text()


# ---- question -> page --------------------------------------------------------------------------------
NOT_SURE = "Ask about a team, a player, two of either side by side, league leaders, standings or a day's games."


def _resolve(name: str, index: list[list]) -> tuple[str, object]:
    abbr = find_team(name)
    if abbr:
        return "team", abbr
    found = find_players(name, index)
    return ("player", found[0]) if len(found) == 1 else ("many", found) if found else ("none", name)


async def answer(q: str, feed, sp: dict | None, hidden: list[dict]) -> tuple[str, dict | None]:
    """The page for a question (OpenUI Lang) and the plan behind it. `feed` is the app's Feed; `hidden` is what
    spoiler-free hides from this person right now (the /api/hidden list): an answer that would give it away isn't
    drawn."""
    try:
        index = await feed.search_index()
    except Exception:
        index = []
    try:
        plan = await understand(q, index)
    except Exception as exc:
        log.warning("ask: model unavailable (%s)", type(exc).__name__)
        return unsure("Ask is warming up", "The question reader isn't running right now. Try again in a minute."), None
    try:
        return await _page(plan, feed, sp, hidden, index), plan
    except Exception:
        log.exception("ask: %s", plan)
        return unsure("NHL data unavailable", "Couldn't load that from the league right now. Try again in a minute."), plan


async def _page(plan: dict, feed, sp: dict | None, hidden: list[dict], index: list[list]) -> str:
    blocked = {t for g in hidden for t in (g["away"]["abbr"], g["home"]["abbr"])}
    if plan["names"]:
        found = [_resolve(n, index) for n in plan["names"]]
        for (kind, what), name in zip(found, plan["names"]):
            if kind == "many":
                return unsure("Which one?", f"More than one player matches “{name}”.", *(r[1] for r in what))
            if kind == "none" and (plan["kind"] == "about" or len(found) == 1):
                return unsure("Couldn't find that", f"No NHL team or player called “{name}”. {NOT_SURE}")
        found = [(k, w) for k, w in found if k != "none"]
        kinds = {k for k, _ in found}
        if kinds == {"team"}:
            abbrs = list(dict.fromkeys(w for _, w in found))
            if blocked & set(abbrs):
                return spoiler_wall("Their record")
            if len(abbrs) == 1:
                rows, sched, team = await asyncio.gather(feed.standings(), feed.team_schedule(abbrs[0]), feed.team(abbrs[0]))
                return team_page(abbrs[0], rows, sched, team["stats"]["skaters"])
            rows, sched = await asyncio.gather(feed.standings(), feed.team_schedule(abbrs[0]))
            return teams_page(abbrs[0], abbrs[1], rows, sched)
        if kinds == {"player"}:
            rows = list({r[0]: r for _, r in found}.values())
            if blocked & {r[2] for r in rows}:
                return spoiler_wall("Their numbers")
            players = await asyncio.gather(*(feed.player(int(r[0])) for r in rows))
            return player_page(players[0], {g["id"] for g in hidden}) if len(players) == 1 else players_page(*players)
        if kinds:
            return unsure("One at a time", "Ask about two teams or two players, not one of each.", *plan["names"])
    if plan["kind"] in ("leaders", "standings") and hidden:
        return spoiler_wall("The league table" if plan["kind"] == "standings" else "The leaders")
    if plan["kind"] == "leaders":
        return leaders_page(plan["stat"] or "points", await feed.leaders("nhl"))
    if plan["kind"] == "standings":
        return standings_page(plan["group"], await feed.standings())
    if plan["kind"] == "games":
        which = plan["day"] or "today"
        today = await feed.today_page()
        slate = today if which == "today" else await feed.day(today["prev" if which == "yesterday" else "next"])
        return games_page(slate, which, sp, feed.opening_day())
    return unsure("I can't answer that yet", NOT_SURE)


async def warm() -> None:
    """Have the model read its instructions once at start-up (~10 s on the VPS), so the first question doesn't wait for
    that. Retries while the model is still loading or stopped."""
    while LLM_URL:
        try:
            await _ask_model(EXAMPLES[0][0])
            return
        except Exception:
            await asyncio.sleep(60)
