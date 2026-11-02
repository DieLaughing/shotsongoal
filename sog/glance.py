"""Short looks at what's going on, built only from copies the app already has: the live dock (your teams' games on now,
on every page) and This just happened (the row on Tonight). Nothing here waits on a league, and spoiler-free stays on the
phone (spoilerHidden in web/app.js), which is what knows about a score someone chose to peek at."""
from __future__ import annotations

import re

MAX_GOALS, MAX_FINALS = 6, 8
CLIP = re.compile(r"-(\d{10,})$")   # a clip's id is the end of its share link (same rule as gameUi.reel in web/app.js)
KEEP = ("id", "league", "date", "start", "state", "period", "clock", "intermission", "outcome")


def brief(g: dict, league: str) -> dict:
    """A game with only what a score line needs."""
    return {**{k: g.get(k) for k in KEEP}, "league": league,
            **{s: {"abbr": g[s]["abbr"], "score": g[s].get("score")} for s in ("away", "home")}}


def live(slates: dict[str, dict], favourites: list[str]) -> list[dict]:
    """Your teams' games that are on or finished today, your first favourite's first. Finals are here so the dock can
    show one that just ended; the phone drops those it never saw live."""
    rank = {a: i for i, a in enumerate(favourites)}
    found = [brief(g, lg) for lg, day in slates.items() for g in day.get("games") or []
             if g.get("state") in ("live", "final") and (g["away"]["abbr"] in rank or g["home"]["abbr"] in rank)]
    last = len(rank)
    return sorted(found, key=lambda g: min(rank.get(g["away"]["abbr"], last), rank.get(g["home"]["abbr"], last)))


def _goals(detail: dict, game: dict) -> list[dict]:
    """A game's goals that have a clip, newest first."""
    found = []
    for per in detail.get("scoring") or []:
        for x in per.get("goals") or []:
            clip = CLIP.search(x.get("clip") or "")
            if clip:
                found.append({"kind": "goal", "game": game, "id": clip[1], "url": x["clip"], "who": x["scorer"], "team": x["team"],
                              "when": f"{per['period']} {x['time']}", "score": f"{x['away']}\u2013{x['home']}"})
    return found[::-1]


def happened(games: list[dict], favourites: list[str], saved) -> list[dict]:
    """The row on Tonight: your teams' latest goals, then finals, yours first. `games` are briefs from today's and
    yesterday's slates, newest last; `saved(game)` is that game's saved page or None. Only your teams' pages are read:
    a copy has to be parsed, and a full slate would be that fifteen times over."""
    mine = set(favourites)
    is_mine = lambda g: g["away"]["abbr"] in mine or g["home"]["abbr"] in mine
    done = sorted((g for g in games if g["state"] in ("live", "final")), key=lambda g: g.get("start") or "", reverse=True)
    pages = {g["id"]: saved(g) or {} for g in done if is_mine(g)}
    goals = [t for g in done if is_mine(g) for t in _goals(pages[g["id"]], g)][:MAX_GOALS]
    finals = sorted((g for g in done if g["state"] == "final"), key=lambda g: not is_mine(g))[:MAX_FINALS]
    return goals + [{"kind": "final", "game": g, "recap": str(r) if (r := (pages.get(g["id"], {}).get("video") or {}).get("recap")) else None}
                    for g in finals]
