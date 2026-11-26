"""The Calendar page (sog/calendar.py): a month of games, your teams' days, showcase games, the season's moments."""
from sog import calendar


def g(gid, day, away, home, league="nhl", event=None, state="pre", a=None, h=None):
    return {"id": gid, "league": league, "date": day, "start": f"{day}T23:00:00Z", "state": state, "venue": "Arena",
            "away": {"abbr": away, "score": a}, "home": {"abbr": home, "score": h}, "event": event}


WC = {"name": "Winter Classic", "kind": "outdoor", "city": "Salt Lake City"}
GAMES = [g(1, "2026-12-23", "BOS", "TOR", state="final", a=3, h=2), g(2, "2026-12-23", "MTL", "OTT"),
         g(3, "2026-12-27", "NYR", "BOS"), g(4, "2026-12-31", "COL", "UTA", event=WC),
         g(4, "2026-12-31", "COL", "UTA", event=WC),                                # the same game from the other team's schedule
         g(9, "2026-12-27", "PW-BOS", "PW-MTL", league="pwhl"), g(5, "2027-01-04", "BOS", "FLA"), g(6, "2026-10-08", "BOS", "CHI")]


def test_a_month_of_days():
    d = calendar.build("2026-12", GAMES, ["BOS"], "2026-12-20", ["nhl", "pwhl"])
    assert len(d["days"]) == 31 and d["days"]["2026-12-23"]["n"] == 2
    assert d["days"]["2026-12-31"]["n"] == 1                                       # counted once
    assert [x["id"] for x in d["days"]["2026-12-23"]["mine"]] == [1]
    assert d["days"]["2026-12-23"]["mine"][0]["away"]["score"] == 3              # the page decides W/L (spoiler-free lives there)
    assert d["days"]["2026-12-27"]["n"] == 2                                       # NHL + PWHL
    assert d["days"]["2026-12-31"]["events"][0]["event"]["name"] == "Winter Classic"
    assert (d["prev"], d["next"]) == ("2026-11", "2027-01")


def test_moments_and_the_christmas_break():
    d = calendar.build("2026-12", GAMES, [], "2026-12-20", ["nhl"])
    keys = {m["key"]: (m["from"], m["to"]) for m in d["moments"]}
    assert keys["freeze"] == ("2026-12-20", "2026-12-27")
    assert keys["wjc"] == ("2026-12-26", "2027-01-05")
    jan = calendar.build("2027-01", GAMES, [], "2026-12-20", ["nhl"])
    assert [m["key"] for m in jan["moments"]] == ["wjc"]                          # runs on into January
    assert keys["break"] == ("2026-12-24", "2026-12-26")
    # The break is the run of game-free days around Christmas, wherever the schedule puts it (2026-27: Dec 23-25).
    moved = [x for x in GAMES if x["date"] != "2026-12-23"] + [g(7, "2026-12-22", "BOS", "NYR"), g(8, "2026-12-26", "TOR", "MTL")]
    assert {m["key"]: (m["from"], m["to"]) for m in calendar.build("2026-12", moved, [], "2026-12-20", ["nhl"])["moments"]}["break"] \
        == ("2026-12-23", "2026-12-25")
    assert "break" not in {m["key"] for m in calendar.build("2026-12", GAMES, [], "2026-12-20", ["pwhl"])["moments"]}


def test_the_ends_of_the_season():
    assert calendar.build("2026-10", GAMES, [], "2026-12-20", ["nhl"])["prev"] is None
    assert calendar.build("2027-01", GAMES, [], "2026-12-20", ["nhl"])["next"] is None
    assert calendar.shift("2026-12", 1) == "2027-01" and calendar.shift("2027-01", -1) == "2026-12"


def test_your_teams_from_every_league_whatever_the_switch_says():
    nhl = [g(1, "2026-12-23", "BOS", "TOR"), g(2, "2026-12-23", "MTL", "OTT")]
    own = [g(9, "2026-12-23", "PW-BOS", "PW-MTL", league="pwhl"), g(77, "2026-12-27", "CM-25", "CM-111", league="ncaam")]
    d = calendar.build("2026-12", nhl, ["PW-BOS", "BOS", "CM-25"], "2026-12-20", ["nhl"], own)
    day = d["days"]["2026-12-23"]
    assert day["n"] == 2                                                   # counts stay NHL-only, as the switch says
    assert [x["league"] for x in day["mine"]] == ["pwhl", "nhl"]          # your first team first: it colours the day
    assert d["days"]["2026-12-27"]["mine"][0]["league"] == "ncaam" and d["days"]["2026-12-27"]["n"] == 0
    college_only = calendar.build("2026-12", [], ["CM-25"], "2026-12-20", [], own)
    assert college_only["leagues"] == [] and college_only["days"]["2026-12-27"]["mine"]
    assert "break" not in {m["key"] for m in college_only["moments"]}
