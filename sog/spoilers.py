"""Spoiler-free mode. settings["spoilers"] = {"teams": [...], "games": [...], "seen": [...]}: teams whose games are
always hidden, games someone marked "watching later", and games they've since watched. Game keys are "nhl:<id>" or
"pwhl:<id>" (the two leagues' ids can collide). The web app mirrors hidden() in web/app.js (spoilerHidden)."""
from __future__ import annotations

import re
from datetime import date, timedelta

KEY = re.compile(r"^(nhl|pwhl):\d{1,12}$")
KEEP = 60  # newest game keys kept per list


def key(g: dict) -> str:
    return f"{'pwhl' if g.get('league') == 'pwhl' else 'nhl'}:{g.get('id')}"


def clean(raw, valid_teams) -> dict:
    raw = raw if isinstance(raw, dict) else {}

    def keys(name):
        out = []
        for k in raw.get(name) or []:
            if isinstance(k, str) and KEY.match(k) and k not in out:
                out.append(k)
        return out[-KEEP:]
    return {"teams": [t for t in raw.get("teams") or [] if t in valid_teams][:44], "games": keys("games"), "seen": keys("seen")}


def hidden(g: dict, sp: dict | None, today: str | None = None) -> bool:
    """True when this person doesn't want to see how the game is going. Only games that have started; with `today`,
    only games from today or yesterday (so a team's old results show again by themselves)."""
    if not sp or g.get("state") not in ("live", "final"):
        return False
    k = key(g)
    if k in (sp.get("seen") or []):
        return False
    if today and (g.get("date") or "") < (date.fromisoformat(today) - timedelta(days=1)).isoformat():
        return False
    return k in (sp.get("games") or []) or bool({g["away"]["abbr"], g["home"]["abbr"]} & set(sp.get("teams") or []))
