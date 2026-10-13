"""Parser, where-to-watch, signed-link and access tests. Fixtures are trimmed copies of real API responses
(2026-10-11)."""
import json
import os
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / f"{name}.json").read_text())


# ---- parsers ---------------------------------------------------------------------
def test_parse_score_live_game():
    from sog import nhl
    day = nhl.parse_score(load("score"))
    g = day["games"][0]
    assert day["date"] == "2026-10-11"
    assert g["state"] == "live" and g["away"]["abbr"] == "SEA" and g["home"]["abbr"] == "WSH"
    assert g["away"]["score"] == 1 and g["clock"] == "03:08" and g["period"] == "1st"
    assert {"network": "Prime Video", "market": "A", "country": "US"} in g["broadcasts"]


def test_parse_detail_final():
    from sog import nhl
    d = nhl.parse_detail(load("landing_final"), load("rail"), load("box"))
    assert d["game"]["state"] == "final"
    first = d["scoring"][0]["goals"][0]
    assert first["scorer"] == "P. Zacha" and first["team"] == "BOS" and first["strength"] == "EV"
    assert d["penalties"][0]["items"][0]["desc"] == "Tripping"
    assert d["stars"][0]["name"] == "F. Minten"
    assert d["linescore"][-1]["period"] == "3rd"
    assert any(s["label"] == "Power play" and s["away"] == "1/3" for s in d["team_stats"])
    assert d["players"]["away"]["skaters"] and d["players"]["home"]["goalies"]


def test_period_labels():
    from sog.nhl import period_label
    assert period_label({"number": 4, "periodType": "OT", "maxRegulationPeriods": 3}) == "OT"
    assert period_label({"number": 6, "periodType": "OT", "maxRegulationPeriods": 3}, 3) == "3OT"
    assert period_label({"number": 5, "periodType": "SO", "maxRegulationPeriods": 3}) == "SO"


def test_parse_standings_and_team_pages():
    from sog import nhl
    rows = nhl.parse_standings(load("standings"))
    assert len(rows) == 32 and {"abbr", "pts", "l10", "wildcard"} <= rows[0].keys()
    assert nhl.parse_club_schedule(load("clubsched"))
    roster = nhl.parse_roster(load("roster"))
    assert {"F", "D", "G"} == {p["group"] for p in roster}
    stats = nhl.parse_club_stats(load("clubstats"))
    assert stats["skaters"][0]["p"] >= stats["skaters"][-1]["p"]


# ---- where to watch ------------------------------------------------------------------
def game(away, home, *casts):
    return {"away": {"abbr": away}, "home": {"abbr": home},
            "broadcasts": [{"network": n, "market": m, "country": c} for n, m, c in casts]}


def test_watch_bruins_on_nesn_even_with_espn_national():
    from sog.watch import watch_for
    w = watch_for(game("BOS", "SJS", ("ESPN", "N", "US"), ("SN+", "N", "CA"), ("NESN", "A", "US")),
                  ["BOS"], ["regional", "espn_plus"])
    assert w["network"] == "NESN" and w["app"] == "NESN 360" and w["have"] is True
    assert w["url"] == "https://watch.nesn.com/"


def test_watch_kings_out_of_market_is_espn_plus():
    from sog.watch import watch_for
    w = watch_for(game("EDM", "LAK", ("ABTV", "H", "US"), ("SN1", "N", "CA")), ["BOS"], ["espn_plus"])
    assert w["network"] == "ESPN+" and w["why"] == "Out of market" and w["have"] is True
    assert w["url"] == "https://plus.espn.com/nhl"
    assert [l["name"] for l in w["links"]] == ["ESPN+", "Hulu"]


def test_watch_tnt_exclusive_beats_local_team():
    from sog.watch import watch_for
    w = watch_for(game("BOS", "NYR", ("TNT", "N", "US"), ("truTV", "N", "US"), ("HBO MAX", "N", "US")),
                  ["BOS"], ["espn_plus"])
    assert w["why"] == "National exclusive" and w["service"] == "tnt" and w["have"] is False


def test_watch_national_alongside_locals_is_blacked_out_for_others():
    from sog.watch import watch_for
    w = watch_for(game("NYR", "PHI", ("TNT", "N", "US"), ("MSG", "A", "US"), ("NBCSP", "H", "US")), ["BOS"], [])
    assert w["network"] == "TNT" and "blacked out" in w["why"]


def test_watch_nhl_network_does_not_block_espn_plus():
    from sog.watch import watch_for
    w = watch_for(game("CHI", "DAL", ("NHLN", "N", "US"), ("CHSN", "A", "US"), ("Prime Video", "H", "US")), ["BOS"], [])
    assert w["network"] == "ESPN+"


def test_watch_espn_plus_exclusive():
    from sog.watch import watch_for
    w = watch_for(game("BOS", "TOR", ("ESPN+", "N", "US"), ("HULU", "N", "US"), ("Disney+", "N", "US")),
                  ["BOS"], ["espn_plus"])
    assert w["network"] == "ESPN+" and w["why"] == "National exclusive" and w["have"] is True


# ---- signed links and the gate ---------------------------------------------------------
def test_signed_links(tmp_path):
    from sog import access
    tok = access.sign(tmp_path, "a@b.com", "approve", "n1", now=1000)
    assert access.verify(tmp_path, tok, now=2000) == {"email": "a@b.com", "action": "approve", "nonce": "n1"}
    assert access.verify(tmp_path, tok, now=1000 + access.LINK_TTL + 1) is None
    body, sig = tok.split(".")
    assert access.verify(tmp_path, f"{body}.{sig[:-2]}xx", now=2000) is None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SOG_DATA", str(tmp_path))
    monkeypatch.setenv("SOG_NO_POLL", "1")
    import importlib
    from sog import access, app as app_mod
    monkeypatch.setattr(access, "ADMIN", "owner@x.com")
    sent = []

    async def fake_notify(*a, **kw):
        sent.append((a, kw))
        return True
    monkeypatch.setattr(access, "notify", fake_notify)
    app_mod = importlib.reload(app_mod)
    from fastapi.testclient import TestClient
    c = TestClient(app_mod.app)
    c.sent = sent
    c.mod = app_mod
    return c


def as_user(monkeypatch, email):
    from sog import access
    monkeypatch.setattr(access, "email_from", lambda headers: email)


def test_gate_request_and_one_tap_approve(client, monkeypatch):
    as_user(monkeypatch, "friend@x.com")
    assert client.get("/api/standings").status_code == 403
    assert client.get("/api/me").json()["status"] == "none"
    assert client.post("/api/request").json()["status"] == "pending"
    assert len(client.sent) == 1
    client.post("/api/request")
    assert len(client.sent) == 1  # no second ping
    from sog import access
    nonce = client.mod.store.user("friend@x.com")["nonce"]
    tok = access.sign(client.mod.DATA_DIR, "friend@x.com", "approve", nonce)
    assert client.post(f"/act/{tok}").status_code == 200
    assert len(client.sent) == 2  # the confirmation push
    assert client.post(f"/act/{tok}").status_code == 200  # a second tap just confirms
    deny = access.sign(client.mod.DATA_DIR, "friend@x.com", "deny", nonce)
    assert client.post(f"/act/{deny}").status_code == 409  # can't flip it with the other button
    assert client.get("/api/me").json()["status"] == "approved"


def test_signed_out_and_admin_only(client, monkeypatch):
    as_user(monkeypatch, None)
    assert client.get("/api/games").status_code == 401
    as_user(monkeypatch, "owner@x.com")
    me = client.get("/api/me").json()
    assert me["admin"] and me["status"] == "approved" and me["settings"]["favorites"] == []
    inv = client.post("/api/admin/invites", json={"note": "Sam"}).json()
    as_user(monkeypatch, "sam@x.com")
    assert client.get("/api/admin").status_code == 403
    r = client.get(f"/invite/{inv['code']}", follow_redirects=False)
    assert r.status_code == 307 and client.mod.store.user("sam@x.com")["status"] == "approved"
    as_user(monkeypatch, "other@x.com")
    assert client.get(f"/invite/{inv['code']}", follow_redirects=False).status_code == 410


def test_settings_are_cleaned(client, monkeypatch):
    as_user(monkeypatch, "owner@x.com")
    client.get("/api/me")
    out = client.put("/api/settings", json={"favorites": ["BOS", "XXX"], "local": ["BOS"],
                                            "services": ["espn_plus", "bogus"]}).json()
    assert out["favorites"] == ["BOS"] and out["local"] == ["BOS"] and out["services"] == ["espn_plus"]
    assert out["notify"] == {"start": True, "goals": True, "final": True, "trades": True}


# ---- the Wire ---------------------------------------------------------------------------
def test_wire_parsers():
    from sog import wire
    moves = wire.parse_moves(load("espn_moves"))
    assert all(m["kind"] == "move" and m["teams"] for m in moves)
    assert any(m["trade"] for m in moves)
    assert wire.parse_moves(load("espn_moves"))[0]["id"] == moves[0]["id"]  # stable across runs
    news = wire.parse_espn_news(load("espn_news"))
    assert news and all(n["url"].startswith("https://") and n["title"] for n in news)
    rss = wire.parse_rss((FIX / "sportsnet.xml").read_text(), "Sportsnet")
    assert rss and all(n["time"] and n["url"] for n in rss)
    posts = wire.parse_bsky(load("bsky"), "notfriedgehnic.bsky.social", "Friedman")
    assert posts and all(p["url"].startswith("https://bsky.app/profile/notfriedgehnic.bsky.social/post/") for p in posts)


def test_team_tagging():
    from sog.wire import teams_in
    assert teams_in("Miner (COL) cleared.") == ["COL"]
    assert set(teams_in("Nashville held Ottawa without a shot")) == {"NSH", "OTT"}
    assert teams_in("Bruins recall Minten; Habs waive a forward") == ["BOS", "MTL"]
    assert teams_in("New York beat the wild crowd") == []  # ambiguous city, common word


def test_espn_abbreviations_map_to_nhl():
    from sog import wire
    data = {"transactions": [{"date": "2026-10-11T07:00Z", "description": "Recalled C X.", "team": {"abbreviation": "LA"}}]}
    assert wire.parse_moves(data)[0]["teams"] == ["LAK"]


def test_calendar_build():
    from sog import ics, nhl
    games = nhl.parse_club_schedule(load("clubsched"))
    for g in games:
        g["watch"] = {"network": "NESN", "app": "NESN 360", "why": "BOS local broadcast"}
    out = ics.build(games, "https://sog.example", "NHL: Bruins")
    assert out.count("BEGIN:VEVENT") == len([g for g in games if g["start"]])
    assert "UID:nhl-" in out and all(len(line.encode()) <= 75 for line in out.split("\r\n"))


def test_calendar_feed_needs_an_approved_token(client, monkeypatch):
    as_user(monkeypatch, "owner@x.com")
    client.get("/api/me")
    tok = client.get("/api/calendar").json()["token"]
    assert client.get("/api/calendar").json()["token"] == tok  # stable
    sched = load("clubsched")

    async def fake_team(abbr):
        from sog import nhl
        return {"schedule": nhl.parse_club_schedule(sched), "roster": [], "stats": {}}
    monkeypatch.setattr(client.mod.feed, "team", fake_team)
    as_user(monkeypatch, None)  # calendar apps have no Cloudflare login
    r = client.get(f"/cal/{tok}/BOS.ics")
    assert r.status_code == 200 and "BEGIN:VCALENDAR" in r.text
    assert client.get("/cal/wrong-token/BOS.ics").status_code == 404
    client.mod.store.set_status("owner@x.com", "revoked")
    assert client.get(f"/cal/{tok}/BOS.ics").status_code == 404


def test_admin_insiders(client, monkeypatch):
    from sog import wire
    as_user(monkeypatch, "owner@x.com")
    ins = client.get("/api/admin").json()["insiders"]
    assert len(ins) == len(wire.DEFAULT_INSIDERS) + len(wire.PWHL_INSIDERS)
    assert {i["league"] for i in ins} == {"nhl", "pwhl"}

    async def fake_check(handle):
        return {"handle": handle, "name": "Someone"} if handle == "someone.bsky.social" else None
    monkeypatch.setattr(wire, "check_handle", fake_check)
    assert client.post("/api/admin/insiders", json={"handle": "@someone"}).status_code == 200
    assert client.post("/api/admin/insiders", json={"handle": "nobody"}).status_code == 404
    handles = [i["handle"] for i in client.get("/api/admin").json()["insiders"]]
    assert "someone.bsky.social" in handles
    client.delete("/api/admin/insiders/someone.bsky.social")
    assert "someone.bsky.social" not in [i["handle"] for i in client.get("/api/admin").json()["insiders"]]



# ---- Phase 3: situations, shot map, recap, alerts ------------------------------------------
def test_situations():
    from sog.nhl import parse_situation
    assert parse_situation("1451", "LAK", "BOS", "REG")["power_play"] == "BOS"
    pulled = parse_situation("0651", "LAK", "BOS", "REG")
    assert pulled["away_pulled"] and pulled["power_play"] is None and pulled["text"] == "LAK goalie pulled"
    assert parse_situation("1551", "LAK", "BOS", "REG") is None
    assert parse_situation("1331", "LAK", "BOS", "OT") is None  # 3-on-3 is normal in overtime


def test_recap_names_the_winner_and_game_winner():
    from sog import nhl
    d = nhl.parse_detail(load("landing_final"), load("rail"), load("box"))
    text = nhl.recap(d)
    assert text.startswith("The Bruins beat the Flyers 5-1 at home.") and "scored the winner" in text


class FakePusher:
    def __init__(self):
        self.sent = []

    async def send(self, sub, payload):
        self.sent.append((sub["endpoint"], payload))
        return "ok"


def _alert_setup(tmp_path):
    from sog import alerts, nhl
    from sog.db import Store
    store = Store(tmp_path / "t.db")
    store.set_status("fan@x.com", "approved")
    store.save_settings("fan@x.com", {"favorites": ["SEA"], "local": ["BOS"], "services": ["espn_plus"]})
    store.add_push("fan@x.com", {"endpoint": "https://push.example/1", "keys": {"p256dh": "k", "auth": "a"}}, "test")
    pusher = FakePusher()
    return store, pusher, alerts.Alerts(store, pusher, "https://sog.example"), nhl.parse_score(load("score"))


def test_alerts_prime_then_send_only_new_goals(tmp_path):
    import asyncio
    store, pusher, al, day = _alert_setup(tmp_path)
    asyncio.run(al.on_day(day))
    assert pusher.sent == []  # first pass after startup just records what already happened
    sea = day["games"][0]
    sea["goals"].append({**sea["goals"][-1], "key": "3-10:00-1", "scorer": "J. Eberle", "away": 9, "home": 2})
    asyncio.run(al.on_day(day))
    asyncio.run(al.on_day(day))
    assert len(pusher.sent) == 1 and "goal" in pusher.sent[0][1]["title"]
    # Yesterday's late game, seen for the first time after a restart: recorded, not replayed.
    asyncio.run(al.on_day({**day, "date": "2026-10-10"}))
    assert len(pusher.sent) == 1


def test_alerts_respect_favorites_and_prefs(tmp_path):
    import asyncio
    store, pusher, al, day = _alert_setup(tmp_path)
    asyncio.run(al.on_day({"date": day["date"], "games": []}))  # prime the date with nothing
    store.save_settings("fan@x.com", {"favorites": ["SEA"], "notify": {"goals": False}})
    asyncio.run(al.on_day(day))
    titles = [p["title"] for _, p in pusher.sent]
    assert titles and all("goal" not in t for t in titles)  # puck drop yes, goals switched off
    assert all("SEA" in t or "Kraken" in t for t in titles)  # Canucks-Rangers isn't a favourite


def test_pbp_shot_map_orientation():
    import json
    from sog import nhl
    raw = json.loads((FIX / "pbp_min.json").read_text())
    shots = nhl.parse_pbp(raw)["shots"]
    home = raw["homeTeam"]["abbrev"]
    on_right = [s["x"] > 0 for s in shots if s["team"] == home]
    assert sum(on_right) >= len(on_right) - 1  # home always shoots right (an odd long shot aside)


# ---- PWHL ------------------------------------------------------------------------------------
def test_pwhl_scorebar_games():
    from sog import pwhl
    games = [pwhl.parse_game(g) for g in load("pwhl_scorebar")]
    g = next(x for x in games if x["id"] == 349)
    assert g["league"] == "pwhl" and g["state"] == "final" and g["outcome"] == "REG"
    assert g["away"]["abbr"] == "PW-MTL" and g["away"]["code"] == "MTL" and g["away"]["score"] == 4
    assert g["start"] == "2026-05-20T23:00:00Z" and g["venue"] == "Canadian Tire Centre"
    ot = next(x for x in games if x["id"] == 211)
    assert ot["outcome"] == "OT"
    assert pwhl.period_label("OT2") == "2OT" and pwhl.period_label("SO") == "SO" and pwhl.period_label("2") == "2nd"


def test_pwhl_detail_shot_map_and_recap():
    from sog import nhl, pwhl
    base = pwhl.parse_game(next(g for g in load("pwhl_scorebar") if g["ID"] == "349"))
    d = pwhl.parse_detail(load("pwhl_summary"), load("pwhl_pxp"), base)
    goals = [x for p in d["scoring"] for x in p["goals"]]
    assert [x["home"] for x in goals] == [0, 0, 0, 0] and goals[-1]["away"] == 4
    assert any(x["strength"] == "SH" for x in goals)
    assert d["stars"][0]["name"] == "A. Roque" and d["game"]["home"]["sog"] == 23
    home = [s for s in d["shotmap"] if s["team"] == "PW-OTT"]
    assert home and all(s["x"] > 0 for s in home)  # home shoots right, like the NHL map
    assert "OTT outshot MTL 23-16" in nhl.recap(d)


def test_pwhl_standings_and_roster():
    from sog import pwhl
    rows = pwhl.parse_standings(load("pwhl_standings"))
    top = rows[0]
    assert top["name"] == "Montréal Victoire" and top["abbr"] == "PW-MTL"  # clinch marker stripped
    assert top["div"] is None
    for r in rows:  # W-OTW-OTL-L must add up to games played and to points (3-2-1-0)
        assert r["w"] + r["otw"] + r["otl"] + r["l"] == r["gp"] and 3 * r["w"] + 2 * r["otw"] + r["otl"] == r["pts"]
    roster = pwhl.parse_roster(load("pwhl_roster"))
    assert roster and {p["group"] for p in roster} <= {"F", "D", "G"}


def test_pwhl_wire_tagging():
    from sog import wire
    assert wire.teams_in("Fleet sign a forward", "pwhl") == ["PW-BOS"]
    assert wire.teams_in("PWHL Detroit names its coach", "pwhl") == ["PW-DET"]
    assert wire.teams_in("Boston Fleet", "nhl") == ["BOS"]  # NHL tagging is untouched
    assert not wire._PWHL_STORY.search("The New York Liberty season ended")


def test_alerts_prime_each_league_separately(tmp_path):
    import asyncio
    store, pusher, al, day = _alert_setup(tmp_path)
    store.save_settings("fan@x.com", {"favorites": ["PW-BOS"]})
    asyncio.run(al.on_day({"date": "2026-12-06", "games": []}))  # the NHL scoreboard primes that date first
    game = {"id": 500, "league": "pwhl", "state": "live", "outcome": None,
            "away": {"abbr": "PW-BOS", "code": "BOS", "name": "Fleet", "score": 1},
            "home": {"abbr": "PW-NY", "code": "NY", "name": "Sirens", "score": 0},
            "goals": [{"key": "1-5:00-x", "period": "1st", "time": "5:00", "team": "PW-BOS", "scorer": "A. Player",
                       "total": 1, "strength": "EV", "empty_net": False, "away": 1, "home": 0}]}
    pday = {"date": "2026-12-06", "league": "pwhl", "games": [game]}
    asyncio.run(al.on_day(pday))
    assert pusher.sent == []  # the PWHL's own first look is recorded, not replayed
    game["goals"].append({**game["goals"][0], "key": "2-1:00-y", "away": 2})
    asyncio.run(al.on_day(pday))
    assert len(pusher.sent) == 1
    assert pusher.sent[0][1]["title"] == "BOS goal · BOS 2-0 NY" and "/#/pgame/500" in pusher.sent[0][1]["url"]


def test_pwhl_team_keys_in_settings(client, monkeypatch):
    as_user(monkeypatch, "owner@x.com")
    client.get("/api/me")
    out = client.put("/api/settings", json={"favorites": ["BOS", "PW-BOS", "PW-XXX"], "local": ["PW-BOS", "BOS"]}).json()
    assert out["favorites"] == ["BOS", "PW-BOS"] and out["local"] == ["BOS"]  # blackouts are NHL-only


def test_pwhl_name_changes():
    from sog import pwhl
    from sog.teams import PWHL
    feed = {"SiteKit": {"Teamsbyseason": [
        {"code": "BOS", "name": "Boston Fleet", "nickname": "Fleet"},          # unchanged
        {"code": "HAM", "name": "PWHL Hamilton", "nickname": "PWHL"},          # not named yet: not a change
        {"code": "DET", "name": "Detroit Example", "nickname": "Example"},     # nickname announced
        {"code": "XYZ", "name": "PWHL Somewhere", "nickname": "PWHL"}]}}      # a team the app doesn't know
    changes = {c["code"]: c for c in pwhl.name_changes(feed, PWHL)}
    assert set(changes) == {"DET", "XYZ"}
    assert changes["DET"]["feed"] == "Example" and changes["DET"]["ours"] == "Detroit"
    assert changes["XYZ"]["ours"] is None


def test_pwhl_name_alert_is_sent_once(client, monkeypatch):
    import asyncio
    sent = []

    async def fake_changes():
        return [{"key": "PW-DET", "code": "DET", "feed": "Example", "ours": "Detroit", "full": "Detroit Example"}]

    async def fake_notify(title, message, **kw):
        sent.append(title)
        return True
    monkeypatch.setattr(client.mod.feed, "pwhl_name_changes", fake_changes)
    monkeypatch.setattr(client.mod.access, "notify", fake_notify)
    assert asyncio.run(client.mod.check_pwhl_names()) == 1
    assert asyncio.run(client.mod.check_pwhl_names()) == 0  # every six hours, but only the first time
    assert sent == ["PWHL: DET is now the Example"]


def test_ticket_links():
    from sog import nhl, pwhl
    g = nhl.parse_game({"id": 1, "gameState": "FUT", "awayTeam": {"abbrev": "BOS"}, "homeTeam": {"abbrev": "SJS"},
                        "ticketsLink": "https://www.ticketmaster.com/event/X"})
    assert g["tickets"] == "https://www.ticketmaster.com/event/X"
    raw = next(x for x in load("pwhl_scorebar") if x["ID"] == "349")
    assert pwhl.parse_game(raw)["tickets"].startswith("https://www.ticketmaster.ca/")  # the feed fills these in
    assert pwhl.parse_game({**raw, "TicketUrl": ""})["tickets"] is None  # finished, no link: nothing to sell
    upcoming = {**raw, "GameStatus": "1", "TicketUrl": ""}
    assert pwhl.parse_game(upcoming)["tickets"] == pwhl.TICKETS  # the league's page until games get their own link
    assert pwhl.parse_game({**upcoming, "TicketUrl": "https://tix.example/1"})["tickets"] == "https://tix.example/1"


# ---- What's new ---------------------------------------------------------------------------------
def test_changelog_matches_changes_yaml():
    """CHANGELOG.md is generated: if this fails, run .venv/bin/python tools/changelog.py."""
    import importlib.util
    from pathlib import Path
    from sog import changes
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("changelog_tool", root / "tools" / "changelog.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    assert (root / "CHANGELOG.md").read_text() == changes.markdown(changes.load(), tool.APP, tool.SITE)


def test_changes_are_well_formed():
    from sog import changes
    entries = changes.load()
    assert entries and len({e["id"] for e in entries}) == len(entries)
    assert [e["date"] for e in entries] == sorted((e["date"] for e in entries), reverse=True)  # newest first
    assert all(e["kind"] in ("new", "improved", "fixed") for e in entries)


def test_whats_new_api_and_seen_marker(client, monkeypatch):
    as_user(monkeypatch, "owner@x.com")
    client.get("/api/me")
    items = client.get("/api/changes").json()
    assert items[0]["title"] and items[0]["id"]
    out = client.put("/api/settings", json={"favorites": ["BOS"], "seen_changes": items[0]["id"]}).json()
    assert out["seen_changes"] == items[0]["id"]


def test_every_nhl_team_has_one_division():
    from sog import teams
    placed = [a for d in teams.DIVISIONS.values() for a in d]
    assert sorted(placed) == sorted(teams.TEAMS) and all(len(d) == 8 for d in teams.DIVISIONS.values())


def test_slate_date_keeps_last_night_until_6am_eastern():
    from datetime import datetime, timezone
    from sog.feed import slate_date
    assert slate_date(datetime(2026, 10, 13, 15, 14, tzinfo=timezone.utc)) == "2026-10-13"  # 11:14 am ET
    assert slate_date(datetime(2026, 10, 14, 5, 30, tzinfo=timezone.utc)) == "2026-10-13"   # 1:30 am ET
    assert slate_date(datetime(2026, 10, 14, 10, 5, tzinfo=timezone.utc)) == "2026-10-14"   # 6:05 am ET
