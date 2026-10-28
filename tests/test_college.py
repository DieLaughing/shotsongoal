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


def test_scores_read_from_the_teams_side():
    assert ncaa.our_score("4-1", "L") == "1-4" and ncaa.our_score("4-3 OT", "L") == "3-4 OT"
    assert ncaa.our_score("5-1", "W") == "5-1" and ncaa.our_score("2-2 OT", "T") == "2-2 OT"


def test_season_summary_from_the_schedule():
    g = lambda gid, away, home, a, h: {"id": gid, "state": "final", "type": 2, "start": f"2026-10-{gid:02d}T23:00:00Z",
                                       "away": {"abbr": away, "score": a}, "home": {"abbr": home, "score": h}}
    sched = [g(3, "CM-113", "CM-2172", 1, 6), g(9, "CM-2511", "CM-113", 2, 2), g(10, "CM-2511", "CM-113", 1, 5),
             g(17, "CM-111", "CM-113", 4, 1), {"id": 30, "state": "pre", "type": 2, "away": {"abbr": "CM-108"}, "home": {"abbr": "CM-113"}}]
    s = ncaa.season_summary(sched, "CM-113", {"CM-113": "HE", "CM-111": "HE", "CM-2172": "NCHC", "CM-2511": "AHA"})
    assert s["record"] == "1-2-1" and s["home"] == "1-1-1" and s["away"] == "0-1-0"
    assert s["conf"] == "0-1-0" and s["conf_name"] == "HE"   # only Northeastern is in Hockey East
    assert s["last"] == ["L", "T", "W", "L"] and s["gf"] == 2.2 and s["ga"] == 3.2
    assert ncaa.season_summary([], "CM-113", {}) is None


def test_roster_and_highlights():
    roster = ncaa.parse_roster({"athletes": [
        {"id": "5", "fullName": "Bo Cosman", "jersey": "28", "position": {"abbreviation": "F"}, "experience": {"years": 3},
         "birthPlace": {"city": "Milton", "state": "GA"}, "displayHeight": "6' 3\""},
        {"id": "6", "fullName": "Jackson Irving", "jersey": "1", "position": {"abbreviation": "G"}, "experience": {"years": 5}}]})
    assert [p["name"] for p in roster] == ["Jackson Irving", "Bo Cosman"]   # by number
    assert roster[1]["year"] == "Jr" and roster[1]["home"] == "Milton, GA" and roster[0]["year"] == "Gr" and roster[0]["group"] == "G"
    vids = ncaa.parse_highlights({"articles": [
        {"type": "Media", "headline": "A vs B Game Highlights", "links": {"web": {"href": "https://espn/x"}},
         "categories": [{"type": "team", "teamId": 113}, {"type": "event", "eventId": 401904769}]},
        {"type": "Story", "headline": "not a video", "links": {"web": {"href": "https://espn/y"}}}]})
    assert vids == [{"title": "A vs B Game Highlights", "url": "https://espn/x", "game": 401904769, "time": None}]


def test_poll_keeps_last_week():
    poll = ncaa.parse_poll({"rankings": [{"ranks": [{"current": 3, "previous": 5, "team": {"id": "2172"}},
                                                   {"current": 20, "previous": 0, "team": {"id": "113"}}]}]})
    assert poll == {"2172": {"rank": 3, "previous": 5}, "113": {"rank": 20, "previous": 0}}
