"""Pre-game matchup: built from the landing + right-rail the game page loads anyway, only before puck drop."""
from sog import nhl

LANDING = {"id": 5, "gameState": "FUT", "awayTeam": {"abbrev": "BUF"}, "homeTeam": {"abbrev": "TOR"}, "matchup": {
    "skaterComparison": {"contextLabel": "last_5_games", "leaders": [
        {"category": "points", "awayLeader": {"name": {"default": "T. Thompson"}, "sweaterNumber": 72, "positionCode": "C", "value": 5},
         "homeLeader": {"name": {"default": "A. Matthews"}, "sweaterNumber": 34, "positionCode": "C", "value": 12}}]},
    "goalieComparison": {"homeTeam": {"leaders": [
        {"name": {"default": "A. Stolarz"}, "sweaterNumber": 41, "gamesPlayed": 3, "record": "2-1-0", "gaa": 3.32, "savePctg": .875},
        {"name": {"default": "S. Bobrovsky"}, "sweaterNumber": 72, "gamesPlayed": 4, "record": "1-2-1", "gaa": 2.97, "savePctg": .907}]}}}}
RAIL = {"last10Record": {"awayTeam": {"record": "3-3-1", "streakType": "O", "streak": 1,
                                      "pastGameResults": [{"opponentAbbrev": "MTL", "gameResult": "SOL"}, {"opponentAbbrev": "FLA", "gameResult": "W"}]},
                         "homeTeam": {"record": "3-3-1", "streakType": "L", "streak": 1, "pastGameResults": []}},
        "teamSeasonStats": {"awayTeam": {"ppPctg": .111, "ppPctgRank": 30, "goalsAgainstPerGamePlayed": 3.57},
                            "homeTeam": {"ppPctg": .29, "ppPctgRank": 5, "goalsAgainstPerGamePlayed": 3.14}},
        "seasonSeries": [{"id": 5}, {"id": 6, "gameDate": "2027-02-27", "gameState": "FUT", "awayTeam": {"abbrev": "TOR"}, "homeTeam": {"abbrev": "BUF"}}],
        "seasonSeriesWins": {"awayTeamWins": 0, "homeTeamWins": 0},
        "gameInfo": {"awayTeam": {"headCoach": {"default": "Lindy Ruff"}, "scratches": [{"firstName": {"default": "J."}, "lastName": {"default": "Doe"}}]}}}


def test_preview_before_puck_drop():
    p = nhl.parse_detail(LANDING, RAIL, None)["preview"]
    assert p["form"]["away"] == {"record": "3-3-1", "streak": "OT1", "last": [{"opp": "MTL", "res": "OT"}, {"opp": "FLA", "res": "W"}]}
    assert [(s["label"], s["away"], s["home"], s["low"]) for s in p["stats"]] == [
        ("Goals against / game", "3.57", "3.14", True), ("Power play", "11%", "29%", False)]
    assert p["hot"][0]["home"] == {"name": "A. Matthews", "number": 34, "pos": "C", "value": 12} and p["hot_context"] == "last 5 games"
    assert [x["name"] for x in p["goalies"]["home"]] == ["S. Bobrovsky", "A. Stolarz"] and p["goalies"]["away"] == []
    assert [x["id"] for x in p["series"]["games"]] == [6]  # this game isn't listed in its own series
    assert p["people"]["away"] == {"coach": "Lindy Ruff", "scratches": ["J. Doe"]}


def test_no_preview_once_the_game_starts():
    assert nhl.parse_detail({**LANDING, "gameState": "LIVE"}, RAIL, None)["preview"] is None
    assert nhl.parse_detail({**LANDING, "matchup": {}}, None, None)["preview"] is None
