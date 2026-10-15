"""Odds: parsing the scoreboard's line, win chances, the saved pre-game line, upsets and the Pick'em bonus."""
import sqlite3
from datetime import datetime, timezone

import pytest

from sog import nhl, odds, picks

NOW = datetime(2026, 10, 20, 20, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    odds.init(conn)
    picks.init(conn)


def g(gid, away, home, state="pre", a=None, h=None, line=None, day="2026-10-20"):
    return {"id": gid, "date": day, "start": f"{day}T23:00:00Z", "state": state, "odds": line,
            "away": {"abbr": away, "score": a}, "home": {"abbr": home, "score": h}}


def test_scoreboard_line_comes_from_the_named_partner():
    raw = {"oddsPartners": [{"partnerId": 7, "name": "FanDuel"}, {"partnerId": 9, "name": "DraftKings"}],
           "games": [{"id": 1, "gameState": "FUT",
                      "awayTeam": {"abbrev": "BUF", "odds": [{"providerId": 7, "value": "+102"}, {"providerId": 9, "value": "-102"}]},
                      "homeTeam": {"abbrev": "TOR", "odds": [{"providerId": 9, "value": "-118"}]}},
                     {"id": 2, "gameState": "OFF", "awayTeam": {"abbrev": "MTL"}, "homeTeam": {"abbrev": "WSH"}}]}
    games = nhl.parse_score(raw)["games"]
    assert games[0]["odds"] == {"away": -102, "home": -118} and games[1]["odds"] is None
    assert odds.american("EVEN") == 100 and odds.american("+150") == 150 and odds.american("") is None


def test_chances_take_out_the_bookmakers_cut():
    assert odds.chances(-102, -118) == (48, 52)
    assert odds.chances(+150, -180) == (38, 62)
    assert sum(odds.chances(-110, -110)) == 100


def test_saved_line_survives_puck_drop_and_marks_upsets():
    odds.note([g(1, "BUF", "TOR", line={"away": +140, "home": -165})])
    odds.note_totals([g(1, "BUF", "TOR")], {("BUF", "TOR"): 7.0})
    final = odds.attach([g(1, "BUF", "TOR", state="final", a=4, h=2)])[0]["odds"]   # the feed has no line any more
    assert final["fav"] == "TOR" and final["upset"] is True and final["scoring"] == "high"
    assert odds.attach([g(1, "BUF", "TOR", state="final", a=1, h=3)])[0]["odds"]["upset"] is False
    assert odds.underdog("nhl", 1) == "away" and odds.underdog("nhl", 99) is None
    odds.note([g(1, "BUF", "TOR", state="live", line={"away": -500, "home": +400})])  # lines after puck drop are ignored
    assert odds.underdog("nhl", 1) == "away"


def test_lines_are_kept_in_memory_and_reloaded():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    odds.init(conn)
    odds.note([g(5, "BOS", "LAK", line={"away": +105, "home": -125})])
    odds.init(conn)  # a restart
    assert odds.underdog("nhl", 5) == "away"


def test_pwhl_games_get_no_odds():
    assert odds.attach([{"id": 1, "league": "pwhl", "state": "pre", "away": {"abbr": "PW-BOS"}, "home": {"abbr": "PW-NY"}}])[0].get("odds") is None


def test_upset_bonus_doubles_and_stacks_with_the_lock(monkeypatch):
    monkeypatch.setattr(picks, "UPSET_FROM", "2026-10-19")
    names = {"a@x": "Al", "b@x": "Bo"}
    odds.note([g(1, "BUF", "TOR", line={"away": +140, "home": -165}), g(2, "DET", "OTT", line={"away": +120, "home": -140})])
    picks.set_pick("a@x", g(1, "BUF", "TOR"), "BUF", now=NOW)                 # underdog, wins: 2
    picks.set_pick("a@x", g(2, "DET", "OTT"), "DET", lock=True, now=NOW)      # underdog lock, wins: 4
    picks.set_pick("b@x", g(1, "BUF", "TOR"), "TOR", now=NOW)                 # favourite, loses: 0
    picks.set_pick("b@x", g(2, "DET", "OTT"), "DET", now=NOW)                 # underdog, wins: 2
    picks.record_results([{**g(1, "BUF", "TOR", "final", 4, 2), "league": "nhl"}, {**g(2, "DET", "OTT", "final", 3, 1), "league": "nhl"}])
    table = picks.board("a@x", names, ["nhl"], "2026-10-20")["table"]
    assert [(r["name"], r["pts"], r["upsets"]) for r in table] == [("Al", 6, 2), ("Bo", 2, 1)]
    mine = picks.for_games("a@x", [g(1, "BUF", "TOR", "final", 4, 2), g(2, "DET", "OTT", "final", 3, 1)], names, now=NOW)
    assert [m["pts"] for m in mine] == [2, 4] and all(m["bonus"] for m in mine)


def test_no_bonus_before_the_start_date(monkeypatch):
    monkeypatch.setattr(picks, "UPSET_FROM", "2026-10-19")
    old = "2026-10-15"
    odds.note([g(1, "BUF", "TOR", line={"away": +140, "home": -165}, day=old)])
    picks.set_pick("a@x", g(1, "BUF", "TOR", day=old), "BUF", now=datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc))
    picks.record_results([{**g(1, "BUF", "TOR", "final", 4, 2, day=old), "league": "nhl"}])
    assert picks.board("a@x", {"a@x": "Al"}, ["nhl"], old)["table"][0]["pts"] == 1


def test_espn_totals_map_abbreviations():
    data = {"events": [{"competitions": [{"odds": [{"overUnder": 5.5}],
                                          "competitors": [{"homeAway": "home", "team": {"abbreviation": "LA"}},
                                                          {"homeAway": "away", "team": {"abbreviation": "BOS"}}]}]}]}
    assert odds.parse_totals(data) == {("BOS", "LAK"): 5.5}
