"""Pick'em: picks lock at puck drop, one lock of the night, results from finals, the table."""
import sqlite3
from datetime import datetime, timezone

import pytest

from sog import picks

NOW = datetime(2026, 10, 13, 20, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def db():
    picks.init(sqlite3.connect(":memory:", check_same_thread=False))


def g(gid, away, home, start="2026-10-13T23:00:00Z", state="pre", a=None, h=None, league="nhl", day="2026-10-13"):
    return {"id": gid, "league": league, "date": day, "start": start, "state": state,
            "away": {"abbr": away, "score": a}, "home": {"abbr": home, "score": h}}


def test_picks_lock_at_puck_drop_and_need_a_real_team():
    picks.set_pick("a@x", g(1, "TOR", "BOS"), "BOS", now=NOW)
    with pytest.raises(ValueError, match="puck drop"):
        picks.set_pick("a@x", g(2, "TOR", "BOS", start="2026-10-13T19:00:00Z"), "BOS", now=NOW)
    with pytest.raises(ValueError, match="puck drop"):
        picks.set_pick("a@x", g(3, "TOR", "BOS", state="live"), "BOS", now=NOW)
    with pytest.raises(ValueError, match="two teams"):
        picks.set_pick("a@x", g(1, "TOR", "BOS"), "MTL", now=NOW)
    picks.set_pick("a@x", g(1, "TOR", "BOS"), None, now=NOW)  # take it back
    assert picks.for_games("a@x", [g(1, "TOR", "BOS")], {"a@x": "A"}, now=NOW)[0]["mine"] is None


def test_one_lock_per_night_and_scoring():
    names = {"a@x": "Al", "b@x": "Bo"}
    picks.set_pick("a@x", g(1, "TOR", "BOS"), "BOS", lock=True, now=NOW)
    picks.set_pick("a@x", g(2, "DET", "OTT"), "OTT", lock=True, now=NOW)       # moves the lock
    picks.set_pick("a@x", g(9, "PW-NY", "PW-BOS", league="pwhl"), "PW-BOS", now=NOW)
    picks.set_pick("b@x", g(1, "TOR", "BOS"), "TOR", now=NOW)
    picks.set_pick("b@x", g(2, "DET", "OTT"), "OTT", now=NOW)
    mine = picks.for_games("a@x", [g(1, "TOR", "BOS"), g(2, "DET", "OTT")], names, now=NOW)
    assert [m["lock"] for m in mine] == [False, True] and mine[0]["picks"] is None  # friends' picks hidden before puck drop
    finals = [g(1, "TOR", "BOS", state="final", a=2, h=4), g(2, "DET", "OTT", state="final", a=3, h=2),
              g(9, "PW-NY", "PW-BOS", state="final", a=1, h=2, league="pwhl")]
    assert picks.record_results(finals) == 5 and picks.record_results(finals) == 0
    shown = picks.for_games("a@x", finals[:1], names, now=NOW)[0]
    assert shown["won"] is True and {p["name"]: p["team"] for p in shown["picks"]} == {"Al": "BOS", "Bo": "TOR"}
    nhl = picks.board("a@x", names, ["nhl"], "2026-10-14")["table"]
    assert [(r["name"], r["pts"], r["w"], r["l"]) for r in nhl] == [("Al", 1, 1, 1), ("Bo", 0, 0, 2)]
    both = picks.board("a@x", names, ["nhl", "pwhl"], "2026-10-14")
    assert both["table"][0] == {"name": "Al", "me": True, "pts": 2, "w": 2, "l": 1}  # the lost lock scores nothing
    assert both["last"]["date"] == "2026-10-13" and both["season"] == "2026-27"


def test_lock_cant_move_off_a_started_game():
    picks.set_pick("a@x", g(1, "TOR", "BOS", start="2026-10-13T20:30:00Z"), "BOS", lock=True, now=NOW)
    later = datetime(2026, 10, 13, 21, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="already on a game"):
        picks.set_pick("a@x", g(2, "DET", "OTT"), "OTT", lock=True, now=later)


def test_seasons_and_weeks():
    assert picks.season_of("2027-03-01") == "2026-27" and picks.season_of("2026-10-13") == "2026-27"
    assert picks.week_start("2026-10-15") == "2026-10-12"
