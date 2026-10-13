"""The "your team" card: results, streaks, the playoff line and the week, from fixtures."""
import json
from pathlib import Path

from sog import home, nhl

FIX = Path(__file__).parent / "fixtures"


def game(gid, d, away, home_, a=None, h=None, state="final", outcome="REG"):
    return {"id": gid, "date": d, "start": f"{d}T23:00:00Z", "state": state, "outcome": outcome if state == "final" else None,
            "away": {"abbr": away, "score": a}, "home": {"abbr": home_, "score": h}}


def test_summary_streak_week_and_next():
    sched = [game(1, "2026-10-01", "BOS", "TOR", 1, 3),            # L
             game(2, "2026-10-08", "MTL", "BOS", 2, 4),            # W
             game(3, "2026-10-10", "BOS", "DET", 3, 2, outcome="OT"),  # W in OT
             game(4, "2026-10-11", "FLA", "BOS", 2, 1, outcome="SO"),  # OT loss
             game(5, "2026-10-13", "TOR", "BOS", state="pre"),
             game(6, "2026-10-15", "BOS", "FLA", state="pre")]
    c = home.team_summary("BOS", sched, [], "2026-10-13")
    assert c["record"] == "2-1-1" and c["streak"] == "OT1"
    assert c["week"] == {"record": "2-0-1", "gf": 8, "ga": 6, "games": 3}  # Oct 1 is more than 7 days back
    assert c["next"]["id"] == 5 and c["after"] == [{"id": 6, "league": "nhl", "date": "2026-10-15",
                                                    "start": "2026-10-15T23:00:00Z", "opp": "FLA", "home": False}]
    assert c["last"]["code"] == "OT" and c["last"]["home"] is True


def test_playoff_line_from_real_standings():
    rows = nhl.parse_standings(json.loads((FIX / "standings.json").read_text()))
    by = {r["abbr"]: home.standing(r["abbr"], rows, "nhl") for r in rows}
    assert by["BOS"]["place"] == "3rd in the Atlantic"
    assert by["BOS"]["race"] == "2 pts above the playoff line"   # 8 pts; FLA (first out) has 6
    assert by["MTL"]["race"] == "1 pt out of a playoff spot"     # 5 pts; WSH (2nd wildcard) has 6
    assert home.ordinal(11) == "11th" and home.ordinal(22) == "22nd"


def test_only_the_latest_season_counts():
    sched = [game(1, "2026-03-10", "BOS", "TOR", 4, 3), game(2, "2026-04-20", "BOS", "TOR", 5, 3),
             game(3, "2026-10-08", "MTL", "BOS", 2, 4), game(4, "2026-10-10", "MTL", "BOS", 2, 4)]
    c = home.team_summary("BOS", sched, [], "2026-10-13")
    assert c["record"] == "2-0-0" and c["streak"] == "W2" and not c["offseason"]
    rows = [{"abbr": "PW-BOS", "league_rank": 2, "pts": 40}]
    off = home.team_summary("PW-BOS", sched[:2], rows, "2026-10-13", "pwhl")
    assert off["offseason"] and off["streak"] is None and off["week"] is None
    assert off["record"] == "2-0-0" and off["standing"]["place"] == "Last season 2nd in the PWHL"
