"""Shots on Goal with fake leagues, for tools/perfcheck.py and CI: every NHL, PWHL, ESPN, MoneyPuck and news request is
answered from tests/fixtures (photos and logos come back "not found"), so timings measure this app's own code and nothing waits on (or bothers) the real sources.

    .venv/bin/python tools/perf_server.py --port 8790 --data /tmp/sog-perf

Signs everyone in as SOG_ADMIN_EMAIL (default perf@example.com) and runs without pollers."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"

NHL = [("game-log", "player_gamelog"), ("player/", "player_landing"), ("skater-stats-leaders", "leaders_skaters"),
       ("goalie-stats-leaders", "leaders_goalies"), ("score/", "score"), ("standings", "standings"), ("/landing", "landing_final"), ("/right-rail", "rail"),
       ("/boxscore", "box"), ("/play-by-play", "pbp_min"), ("club-schedule", "clubsched"), ("roster/", "roster"),
       ("club-stats", "clubstats")]
PWHL = {"scorebar": "pwhl_scorebar", "standings": "pwhl_standings", "roster": "pwhl_roster",
        "gamesummary": "pwhl_summary", "pxpverbose": "pwhl_pxp", "profile": "pwhl_player_profile",
        "seasonstats": "pwhl_player_seasonstats", "gamebygame": "pwhl_player_gamebygame", "topscorers": "pwhl_topscorers",
        "topgoalies": "pwhl_topgoalies"}
WIRE = [("transactions", "espn_moves.json"), ("/news", "espn_news.json"), ("bsky", "bsky.json"),
        ("sportsnet", "sportsnet.xml"), ("rss", "sportsnet.xml"), ("feed", "sportsnet.xml")]   # any RSS: Sportsnet's


class Missing(Exception):
    """A request the fixtures don't cover: the app treats it like a source being down."""


def _json(name: str):
    return json.loads((FIX / f"{name}.json").read_text())


class _Reply:
    def __init__(self, text: str):
        self.text = text

    def json(self):
        return json.loads(self.text)


def install() -> None:
    from sog import images, moneypuck, ncaa, nhl, odds, pwhl, wire

    async def nhl_get(path: str) -> dict:
        for part, name in NHL:
            if part in path:
                return _json(name)
        raise Missing(path)

    async def pwhl_get(**params) -> dict:
        for part, name in PWHL.items():
            if part in (params.get("category"), params.get("view"), params.get("type"), params.get("tab")):
                return _json(name)
        raise Missing(str(params))

    async def ncaa_get(league: str, path: str, base: str = "", **params) -> dict:   # college: one Saturday's slate
        if path == "scoreboard":
            return _json("ncaa_scoreboard")
        if path == "standings":
            return _json("ncaa_standings")
        raise Missing(path)

    async def wire_get(url: str, **params) -> _Reply:
        for part, name in WIRE:
            if part in url:
                return _Reply((FIX / name).read_text())
        raise Missing(url)

    async def moneypuck_get(url: str) -> str:
        return (FIX / ("moneypuck_goalies.csv" if "goalies" in url else "moneypuck_skaters.csv")).read_text()

    async def no_images(self, url: str) -> bytes:   # photos and logos: "not found", so pages draw without them
        raise images.Missing(url)

    nhl.get, pwhl.get, ncaa.get, wire._get, odds.get_url = nhl_get, pwhl_get, ncaa_get, wire_get, wire_get
    moneypuck.get, images.Images._get = moneypuck_get, no_images


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--data", required=True, help="an empty folder for the database")
    args = ap.parse_args()
    email = os.environ.setdefault("SOG_ADMIN_EMAIL", "perf@example.com")
    os.environ.update(SOG_DATA=args.data, SOG_LOCAL_EMAIL=email, SOG_NO_POLL="1")
    sys.path.insert(0, str(ROOT))
    install()
    import uvicorn
    uvicorn.run("sog.app:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
