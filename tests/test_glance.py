"""The live dock and This just happened: built from saved copies, in the order people expect."""
import json
from pathlib import Path

from sog import glance, nhl
from test_core import as_user, client  # noqa: F401  (the app fixture)

FIX = Path(__file__).parent / "fixtures"


def game(gid, away, home, state="live", start="2026-11-01T23:00:00Z", **more):
    return {"id": gid, "state": state, "start": start, "away": {"abbr": away, "score": 1}, "home": {"abbr": home, "score": 0}, **more}


def test_the_dock_lists_your_teams_first_favourite_first():
    slates = {"nhl": {"games": [game(1, "BOS", "TOR"), game(2, "LAK", "EDM"), game(3, "SEA", "VAN"), game(4, "MTL", "OTT", state="pre")]},
              "pwhl": {"games": [game(5, "PW-BOS", "PW-MTL", state="final")]}}
    found = glance.live(slates, ["LAK", "PW-BOS", "BOS", "MTL"])
    assert [g["id"] for g in found] == [2, 5, 1]             # not someone else's game, not one that hasn't started
    assert found[1]["league"] == "pwhl" and set(found[0]["away"]) == {"abbr", "score"}


def test_happened_is_your_goals_then_finals_yours_first():
    landing = json.loads((FIX / "landing_final.json").read_text())
    detail = nhl.parse_detail(landing, {"gameVideo": {"threeMinRecap": 11, "condensedGame": 22}}, None)
    detail["scoring"] = [{"period": "1st", "goals": [
        {"scorer": "A. One", "team": "BOS", "time": "04:00", "away": 1, "home": 0, "clip": "https://nhl.com/video/one-6400000000111"},
        {"scorer": "B. Two", "team": "BOS", "time": "09:00", "away": 2, "home": 0, "clip": "https://nhl.com/video/two-6400000000222"},
        {"scorer": "C. Three", "team": "TOR", "time": "12:00", "away": 2, "home": 1, "clip": None}]}]
    games = [glance.brief(game(1, "SEA", "VAN", state="final", start="2026-11-02T02:00:00Z"), "nhl"),
             glance.brief(game(2, "BOS", "TOR", state="final", start="2026-11-01T23:00:00Z"), "nhl"),
             glance.brief(game(3, "MTL", "OTT", state="pre"), "nhl")]
    read = []
    tiles = glance.happened(games, ["BOS"], lambda g: read.append(g["id"]) or detail)
    assert [t.get("who") or t["game"]["id"] for t in tiles] == ["B. Two", "A. One", 2, 1]  # newest goal first; no clip, no tile
    assert tiles[0]["id"] == "6400000000222" and tiles[0]["score"] == "2–0" and tiles[0]["when"] == "1st 09:00"
    assert tiles[2]["recap"] == "11" and tiles[3]["recap"] is None
    assert read == [2]                                        # other people's games are never parsed


def test_nothing_saved_yet_is_just_fewer_tiles():
    assert glance.happened([glance.brief(game(1, "BOS", "TOR"), "nhl")], ["BOS"], lambda g: None) == []


def test_the_routes_answer_with_no_favourites(client, monkeypatch):  # noqa: F811
    as_user(monkeypatch, "owner@x.com")
    assert client.get("/api/live").json() == {"games": []}
    assert client.get("/api/happened?leagues=nonsense").json() == {"tiles": []}
