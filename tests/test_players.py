"""Player pages, leaders, search, MoneyPuck and images. Fixtures are trimmed real responses from 2026-10-17."""
import asyncio
import io
import time
from pathlib import Path

from PIL import Image

from test_core import as_user, client, load  # noqa: F401  (the app fixture)

FIX = Path(__file__).parent / "fixtures"


# ---- parsers ---------------------------------------------------------------------------------
def test_nhl_skater_and_goalie_pages():
    from sog import nhl
    p = nhl.parse_player(load("player_landing"))
    assert p["name"] == "David Pastrnak" and p["team"] == "BOS" and not p["goalie"]
    assert p["season"]["label"] == "2026-27" and p["season"]["toi"] == "19:35"
    assert p["career"]["regular"]["p"] == 943 and p["seasons"][0]["season"] == "2026-27"
    g = nhl.parse_player(load("player_landing_g"))
    assert g["goalie"] and g["draft"] == "2017 · Round 4 · #111 overall (BOS)"
    assert g["season"]["w"] == 5 and g["awards"][0]["seasons"] == ["2022-23"]
    log = nhl.parse_game_log(load("player_gamelog_g"), True)
    assert log[0]["dec"] == "W" and log[0]["opp"] == "SJS" and not log[0]["home"]


def test_nhl_names_carry_player_ids():
    from sog import nhl
    d = nhl.parse_detail(load("landing_final"), load("rail"), load("box"))
    goal = d["scoring"][0]["goals"][0]
    assert isinstance(goal["pid"], int) and all(isinstance(a["pid"], int) for a in goal["assists"])
    assert all(isinstance(s["pid"], int) for s in d["stars"])
    assert all(isinstance(x["pid"], int) for x in d["players"]["home"]["skaters"])
    assert all(isinstance(x["pid"], int) for x in nhl.parse_club_stats(load("clubstats"))["skaters"])


def test_leaders_both_leagues():
    from sog import nhl, pwhl
    n = nhl.parse_leaders(load("leaders_skaters"), load("leaders_goalies"))
    assert set(n) == set(nhl.LEADER_CATS) and n["points"][0]["name"] == "Connor McDavid"
    p = pwhl.parse_leaders(load("pwhl_topscorers"), load("pwhl_topgoalies"))
    assert p["points"][0]["team"].startswith("PW-")
    assert [r["value"] for r in p["goals"]] == sorted((r["value"] for r in p["goals"]), reverse=True)
    gaa = [r["value"] for r in p["goalsAgainstAverage"]]
    assert gaa == sorted(gaa)


def test_pwhl_player_pages():
    from sog import pwhl
    p = pwhl.parse_player(load("pwhl_player_profile"), load("pwhl_player_seasonstats"), load("pwhl_player_gamebygame"), 12)
    assert p["name"] == "Megan Keller" and p["team"] == "PW-BOS" and p["pos"] == "D"
    assert p["career"]["regular"]["gp"] > p["season"]["gp"] and p["log"][0]["opp"].startswith("PW-")
    g = pwhl.parse_player(load("pwhl_goalie_profile"), load("pwhl_goalie_seasonstats"), load("pwhl_goalie_gamebygame"), 262)
    assert g["goalie"] and g["log"][0]["dec"] in ("W", "L", "OT") and 0 < g["log"][0]["svpct"] <= 1


def test_moneypuck_numbers_and_percentiles():
    from sog import moneypuck
    m = moneypuck.parse((FIX / "moneypuck_skaters.csv").read_text(), (FIX / "moneypuck_goalies.csv").read_text())
    pasta, sway = m["8477956"], m["8480280"]
    assert not pasta["goalie"] and pasta["xg"] > 0 and 0 < pasta["xgf"] < 100 and 0 <= pasta["pct"]["xg"] <= 100
    assert sway["goalie"] and sway["gsax"] == round(sway["xga"] - sway["ga"], 1)


# ---- images ----------------------------------------------------------------------------------
def test_photos_shrunk_cached_and_misses_remembered(tmp_path):
    from sog import images
    src = io.BytesIO()
    Image.new("RGBA", (336, 336), (200, 30, 30, 255)).save(src, "PNG")
    calls = []

    async def fake_get(self, url):
        calls.append(url)
        if "/404/" in url or url.endswith("/1.png"):
            raise images.Missing(url)
        return src.getvalue()
    imgs = images.Images(tmp_path, lambda: "20262027")
    imgs._get = fake_get.__get__(imgs)
    path = asyncio.run(imgs.photo("nhl", "BOS", 8477956, 96))
    assert path and path.stat().st_size < 4000 and (tmp_path / "p/nhl/BOS/8477956-192.webp").exists()
    asyncio.run(imgs.photo("nhl", "BOS", 8477956, 192))
    assert len(calls) == 1                          # one download makes every size
    assert asyncio.run(imgs.photo("nhl", "BOS", 1, 96)) is None
    assert asyncio.run(imgs.photo("nhl", "BOS", 1, 96)) is None and len(calls) == 2   # the miss is remembered


def test_photo_falls_back_to_the_players_own_headshot(tmp_path):
    from sog import images
    src = io.BytesIO()
    Image.new("RGB", (240, 240)).save(src, "JPEG")
    seen = []

    async def fake_get(self, url):
        seen.append(url)
        if "20262027" in url:
            raise images.Missing(url)
        return src.getvalue()

    async def fallback(pid):
        return f"https://example.test/old/{pid}.png"
    imgs = images.Images(tmp_path, lambda: "20262027", fallback)
    imgs._get = fake_get.__get__(imgs)
    assert asyncio.run(imgs.photo("nhl", "BOS", 8480280, 96))
    assert seen[-1] == "https://example.test/old/8480280.png"


# ---- API -------------------------------------------------------------------------------------
def _fake_leagues(monkeypatch):
    from sog import images, moneypuck, nhl, pwhl

    async def nhl_get(path):
        if "game-log" in path:
            return load("player_gamelog")
        if path.startswith("player/"):
            return load("player_landing")
        if "skater-stats-leaders" in path:
            return load("leaders_skaters")
        if "goalie-stats-leaders" in path:
            return load("leaders_goalies")
        if path.startswith("roster/"):
            return load("roster")
        raise LookupError(path)

    async def pwhl_get(**params):
        name = {"profile": "pwhl_player_profile", "seasonstats": "pwhl_player_seasonstats",
                "gamebygame": "pwhl_player_gamebygame"}.get(params.get("category"))
        if name:
            return load(name)
        if params.get("view") == "seasons":
            return {"SiteKit": {"Seasons": [{"season_id": "8", "season_name": "2025-26 Regular Season", "career": "1",
                                             "playoff": "0", "start_date": "2025-11-21", "end_date": "2026-04-25"}]}}
        if params.get("view") == "roster":
            return load("pwhl_roster")
        raise LookupError(str(params))

    async def mp_get(url):
        return (FIX / ("moneypuck_goalies.csv" if "goalies" in url else "moneypuck_skaters.csv")).read_text()

    async def no_images(self, url):
        raise images.Missing(url)
    monkeypatch.setattr(nhl, "get", nhl_get)
    monkeypatch.setattr(pwhl, "get", pwhl_get)
    monkeypatch.setattr(moneypuck, "get", mp_get)
    monkeypatch.setattr(images.Images, "_get", no_images)


def test_player_page_api(client, monkeypatch):
    _fake_leagues(monkeypatch)
    as_user(monkeypatch, "owner@x.com")
    r = client.get("/api/player/8477956")
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "David Pastrnak" and d["log"] and d["seasons"]
    # MoneyPuck never holds up the page: the first visit starts the download, a later one shows the numbers.
    for _ in range(50):
        if client.get("/api/player/8477956").json().get("advanced"):
            break
        time.sleep(0.02)
    d = client.get("/api/player/8477956").json()
    assert d["advanced"]["xg"] > 0 and d["credit"] == "https://moneypuck.com"
    assert client.get("/api/player/12ab").status_code == 404
    assert client.get("/api/pwhl/player/12").json()["name"] == "Megan Keller"


def test_leaders_and_search_api(client, monkeypatch):
    _fake_leagues(monkeypatch)
    as_user(monkeypatch, "owner@x.com")
    assert client.get("/api/leaders").json()["cats"]["points"][0]["name"] == "Connor McDavid"
    rows = client.get("/api/search").json()["players"]
    assert rows and all(isinstance(r[0], int) and r[1] for r in rows)
    assert any(r[2].startswith("PW-") for r in rows) and any(r[2] == "BOS" for r in rows)


def test_image_routes_reject_made_up_names(client, monkeypatch):
    _fake_leagues(monkeypatch)
    as_user(monkeypatch, "owner@x.com")
    for path in ("/img/p/nhl/XXX/8477956-96.webp", "/img/p/nhl/BOS/8477956-50.webp", "/img/p/nhl/BOS/..%2Fsog.db",
                 "/img/p/pwhl/BOS/12-96.webp"):
        assert client.get(path).status_code == 404, path
    assert client.get("/img/p/nhl/BOS/8477956-96.webp").status_code == 404   # the league has no photo: a plain miss


def test_marks_and_photos_settings(client, monkeypatch):
    as_user(monkeypatch, "owner@x.com")
    s = client.put("/api/settings", json={"marks": "logos", "photos": False}).json()
    assert s["marks"] == "logos" and s["photos"] is False
    s = client.put("/api/settings", json={"marks": "<script>"}).json()
    assert s["marks"] == "logos" and s["photos"] is True
    assert client.put("/api/settings", json={"marks": "badges"}).json()["marks"] == "badges"


def test_logos_are_one_stylesheet(tmp_path):
    """Every logo in one CSS file, light and dark; a team without a logo gets no rule (and keeps its badge)."""
    from sog import images
    png = io.BytesIO()
    Image.new("RGBA", (200, 120), (10, 80, 60, 255)).save(png, "PNG")

    async def fake_get(self, url):
        if "/tor.png" in url:
            raise images.Missing(url)
        if "500-dark" in url:   # a different dark version: it gets its own rule
            out = io.BytesIO()
            Image.new("RGBA", (200, 120), (240, 240, 240, 255)).save(out, "PNG")
            return out.getvalue()
        return png.getvalue()
    imgs = images.Images(tmp_path, lambda: "20262027")
    imgs._get = fake_get.__get__(imgs)
    path = asyncio.run(images.logos_css(imgs, ["BOS", "TOR"], {"PW-BOS": 1}))
    css = path.read_text()
    assert ".mark.lg-BOS{background:url(\"data:image/webp;base64," in css and "lg-TOR" not in css
    assert ".mark.lg-PW-BOS{background:url(\"data:image/webp;base64," in css
    assert css.index("@media (prefers-color-scheme: dark)") < css.rindex(".mark.lg-BOS{background-image")
    assert images.css_version(path) and len(images.css_version(path)) == 10


def test_me_offers_logos_unless_badges_are_picked(client, monkeypatch):
    _fake_leagues(monkeypatch)
    as_user(monkeypatch, "owner@x.com")
    assert client.get("/api/me").json()["settings"]["marks"] == "logos"   # the default, before anyone picks
    client.put("/api/settings", json={"marks": "badges"})
    assert client.get("/api/me").json()["logos"] is None
    client.put("/api/settings", json={"marks": "logos"})
    assert "logos" in client.get("/api/me").json()   # None until built (badges meanwhile), then a versioned URL
