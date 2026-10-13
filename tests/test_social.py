"""Friends on every game: watching, reactions, rivalries, clean-up."""
import sqlite3

import pytest

from sog import alerts, social


@pytest.fixture(autouse=True)
def db():
    social.init(sqlite3.connect(":memory:", check_same_thread=False))


PEOPLE = social.friends([
    {"email": "me@x", "status": "approved", "settings": {"nickname": "JC", "favorites": ["BOS", "LAK", "PW-BOS"]}},
    {"email": "dave@x", "status": "approved", "settings": {"favorites": ["TOR", "BOS"]}},
    {"email": "mike@x", "status": "approved", "settings": {"nickname": "Mike", "favorites": ["PW-TOR", "LAK"]}},
    {"email": "gone@x", "status": "revoked", "settings": {"favorites": ["TOR"]}},
])


def game(state="live", a=None, h=None, league="nhl"):
    return {"id": 5, "league": league, "date": "2026-10-13", "state": state,
            "away": {"abbr": "TOR", "score": a}, "home": {"abbr": "BOS", "score": h}}


def test_names_and_rivals():
    assert PEOPLE["dave@x"]["name"] == "dave" and "gone@x" not in PEOPLE
    assert social.rivals("me@x", game(), PEOPLE) == [{"name": "dave", "team": "TOR"}]   # Dave's main team is the Leafs
    assert social.rivals("dave@x", game(), PEOPLE) == []  # Dave likes both teams here, so nobody is on "the other side"


def test_watching_and_reactions():
    g = game()
    social.set_watching("me@x", g, True)
    social.set_watching("dave@x", g, True)
    social.react("dave@x", g, "g:1st-04:18-A. Matthews", "😭")
    social.react("me@x", g, "g:1st-04:18-A. Matthews", "🔥")
    social.react("me@x", g, "g:1st-04:18-A. Matthews", "😭")       # changing your mind replaces it
    out = social.for_game("me@x", g, PEOPLE)
    assert out["me_watching"] and [w["name"] for w in out["watching"]] == ["JC", "dave"]
    assert out["reactions"] == {"g:1st-04:18-A. Matthews": {"😭": 2}} and out["mine"] == {"g:1st-04:18-A. Matthews": "😭"}
    with pytest.raises(ValueError):
        social.react("me@x", g, "g:x", "💩")
    with pytest.raises(ValueError):
        social.react("me@x", game(state="pre"), "g:1st-04:18-A. Matthews", "🔥")
    social.cleanup("2027-07-02")                                    # new season: everything goes
    assert social.for_game("me@x", g, PEOPLE)["reactions"] == {} and not social.for_game("me@x", g, PEOPLE)["watching"]


def test_final_alert_rivalry_line():
    won = game("final", 2, 4)
    assert alerts.rivalry_line("me@x", won, {"BOS"}, PEOPLE) == " · Tell dave."
    assert alerts.rivalry_line("me@x", game("final", 5, 1), {"BOS"}, PEOPLE) == " · dave will enjoy this one."
    assert alerts.rivalry_line("mike@x", won, {"LAK"}, PEOPLE) == ""
