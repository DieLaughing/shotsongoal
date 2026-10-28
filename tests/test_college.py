"""College hockey (ESPN): parsing, ties, goal alerts from the score, where to watch. Fixtures are trimmed real
responses from 2026-10-24."""
import json
from pathlib import Path

from sog import alerts, home, ncaa, social, spoilers, teams, watch

FIX = Path(__file__).parent / "fixtures"


def day():
    return ncaa.parse_scoreboard(json.loads((FIX / "ncaa_scoreboard.json").read_text()), "ncaam", "2026-10-24", {"2172": 3})


def test_scoreboard_games_ties_ranks_and_streams():
    d = day()
    by = {g["away"]["code"]: g for g in d["games"]}
    tie = by["BC"]
    assert tie["state"] == "final" and tie["outcome"] == "T" and tie["away"]["score"] == tie["home"]["score"] == 2
    assert tie["home"]["abbr"] == "CM-2172" and tie["home"]["rank"] == 4   # ESPN's own rank beats the saved poll
    assert tie["away"]["periods"] == [0, 1, 1, 0] and tie["networks"] == ["NCHCHockey.com"]
    assert by["CAN"]["outcome"] == "OT" and by["UML"]["outcome"] == "REG"
    assert by["UML"]["home"]["rank"] == 7 and by["UML"]["away"]["rank"] is None   # 99 = unranked
    assert all(g["date"] == "2026-10-24" and g["start"].endswith(":00Z") for g in d["games"])
    assert d["prev"] and d["prev"] < "2026-10-24"


def test_teams_are_known_and_keyed_by_league():
    g = day()["games"][0]
    assert g["away"]["abbr"] in teams.ALL and g["home"]["abbr"] in teams.ALL
    assert teams.league_of("CM-103") == "ncaam" and teams.league_of("CW-103") == "ncaaw" and teams.league_of("PW-BOS") == "pwhl"
    assert teams.COLLEGE_INFO["CM-103"]["conf"] == "HE"
    women = {t["school"]: t["conf"] for k, t in teams.COLLEGE_INFO.items() if k.startswith("CW-")}
    assert women["Wisconsin"] == "WCHA" and women["Boston College"] == "HE"


def test_standings_sort_by_win_percentage_within_conference():
    rows = ncaa.parse_standings(json.loads((FIX / "ncaa_standings.json").read_text()), "ncaam", {})
    for conf in {r["conf"] for r in rows}:
        mine = [r for r in rows if r["conf"] == conf]
        assert [r["div_rank"] for r in mine] == list(range(1, len(mine) + 1))
        assert [r["pct"] for r in mine] == sorted((r["pct"] for r in mine), reverse=True)


def test_ties_on_the_team_card():
    g = next(x for x in day()["games"] if x["outcome"] == "T")
    r = home.result(g, "CM-2172")
    assert r["code"] == "T"
    assert home.record([r, {**r, "code": "W"}, {**r, "code": "OT"}]) == "1-1-1"   # college: W-L-T, OT losses are losses
    assert home.standing("CM-2172", [{"abbr": "CM-2172", "rank": 3, "w": 1, "l": 0, "t": 0}], "ncaam")["place"] == "No. 3 in the poll"


def test_goal_alerts_from_the_score():
    g = next(x for x in day()["games"] if x["away"]["code"] == "UML")
    g = {**g, "goals": ncaa.goals(g)}
    events = alerts.Alerts(None, None, "https://x").game_events({"league": "ncaam", "date": g["date"], "games": [g]})
    goals = [e for e in events if e["kind"] == "goals"]
    assert len(goals) == g["away"]["score"] + g["home"]["score"]
    assert len({e["key"] for e in goals}) == len(goals) and all(e["key"].startswith(f"goal:ncaam:{g['id']}:") for e in goals)
    assert goals[0]["url"] == f"https://x/#/cgame/ncaam/{g['id']}" and "UML goal" in goals[0]["title"]
    final = next(e for e in events if e["kind"] == "final")
    assert final["title"].startswith("Final:")


def test_where_to_watch_college():
    g = {"networks": ["B1G+"]}
    assert watch.college(g, ["b1g_plus"])["have"] is True
    assert watch.college(g, [])["have"] is False and watch.college(g, None)["have"] is None
    assert watch.college(g, ["b1g_plus"], "CA")["have"] is None
    both = watch.college({"networks": ["Midco Sports Net", "ESPN+"]}, ["espn_plus"])
    assert both["app"] == "ESPN+" and both["links"][0]["name"] == "ESPN+"   # the one you have leads
    assert watch.college({"networks": []}, [])["why"] == "No stream listed yet"


def test_keys_carry_the_league():
    g = {"league": "ncaaw", "id": 401905141}
    assert spoilers.key(g) == "ncaaw:401905141" and social.league(g) == "ncaaw"
    assert spoilers.clean({"games": ["ncaaw:401905141", "bad:1"]}, teams.ALL)["games"] == ["ncaaw:401905141"]
