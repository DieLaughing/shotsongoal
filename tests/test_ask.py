"""Ask: reading names, the plan, and the OpenUI Lang pages built from the app's own data."""
import asyncio
import re

import pytest

from sog import ask

INDEX = [[8477956, "David Pastrnak", "BOS", "R"], [8478483, "Mitch Marner", "VGK", "R"], [8480069, "Jeremy Swayman", "BOS", "G"],
         [8478402, "Connor McDavid", "EDM", "C"], [8480027, "Tim Stützle", "OTT", "C"], [8476453, "Nikita Kucherov", "TBL", "R"],
         [8479318, "Auston Matthews", "TOR", "C"], [8481540, "Cole Caufield", "MTL", "R"], [8480012, "Elias Pettersson", "VAN", "C"],
         [8483678, "Elias Pettersson", "VAN", "D"], [1, "Sarah Nurse", "PW-VAN", "F"]]


def row(abbr, conf, div, pts, gp=10, **kw):
    return {"abbr": abbr, "conf": conf, "div": div, "gp": gp, "w": pts // 2, "l": gp - pts // 2, "otl": pts % 2, "pts": pts, "rw": 3,
            "gd": kw.get("gd", 0), "gf": 30, "ga": 30, "l10": "5-4-1", "streak": "W2", "div_rank": kw.get("rank", 1),
            "league_rank": kw.get("rank", 1)}


ROWS = [row("BOS", "Eastern", "Atlantic", 15, gd=6, rank=1), row("TOR", "Eastern", "Atlantic", 12, gd=-2, rank=2),
        row("LAK", "Western", "Pacific", 14, gd=3), row("ANA", "Western", "Pacific", 9, gd=-5, rank=2)]


def game(gid, away, home, a=None, h=None, state="final", day="2026-10-20"):
    return {"id": gid, "date": day, "start": f"{day}T23:00:00Z", "state": state, "type": 2,
            "away": {"abbr": away, "score": a}, "home": {"abbr": home, "score": h}}


class Feed:
    def __init__(self):
        self.asked = []

    def opening_day(self):
        return "2026-10-21"

    async def search_index(self):
        return INDEX

    async def standings(self):
        return ROWS

    async def team_schedule(self, abbr):
        self.asked.append(abbr)
        return [game(1, "TOR", "BOS", 2, 4), game(2, "BOS", "LAK", 1, 3, day="2026-10-18"),
                game(3, "BOS", "TOR", state="pre", day="2026-10-25")]

    async def team(self, abbr):
        return {"stats": {"skaters": [{"name": "David Pastrnak", "p": 12, "g": 6}, {"name": "Pavel Zacha", "p": 8, "g": 3}]}}

    async def player(self, pid):
        return {"id": pid, "name": next(r[1] for r in INDEX if r[0] == pid), "number": 88, "pos": "R", "team": "BOS", "goalie": False,
                "season": {"label": "2026-27", "gp": 10, "g": 6, "a": 6, "p": 12, "pm": 3, "shots": 40, "ppg": 2},
                "log": [{"date": "2026-10-20", "game": 1, "opp": "TOR", "g": 2, "a": 1, "p": 3, "shots": 5},
                        {"date": "2026-10-18", "game": 2, "opp": "LAK", "g": 0, "a": 1, "p": 1, "shots": 3}]}

    async def leaders(self, league):
        return {"season": "2026-27", "cats": {"goals": [{"pid": 8477956, "name": "David Pastrnak", "team": "BOS", "value": 9}]}}

    async def today_page(self):
        return {"date": "2026-10-21", "prev": "2026-10-20", "next": "2026-10-22",
                "games": [game(4, "TOR", "BOS", 1, 2, state="live", day="2026-10-21"), game(5, "LAK", "ANA", state="pre", day="2026-10-21")]}

    async def day(self, d):
        return {"date": d, "games": [game(1, "TOR", "BOS", 2, 4)]}


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    ask._plans.clear()
    monkeypatch.setattr(ask, "LLM_URL", "http://model")
    plans = {}

    async def fake(q):
        return plans[q]
    monkeypatch.setattr(ask, "_ask_model", fake)
    return plans


def run(q, hidden=(), sp=None):
    lang, plan = asyncio.run(ask.answer(q, Feed(), sp, list(hidden)))
    return lang, plan


def well_formed(lang):
    """root first; every bN it uses is defined once and every definition is used."""
    lines = lang.split("\n")
    assert lines[0].startswith("root = Card([")
    used = re.findall(r"b\d+", lines[0])
    defined = [ln.split(" = ", 1)[0] for ln in lines[1:]]
    assert used == defined
    assert lang.count("(") == lang.count(")") or '"(' in lang or '("' in lang


def test_team_names_people_type():
    assert ask.find_team("Bruins") == "BOS"
    assert ask.find_team("the B's") == "BOS"
    assert ask.find_team("habs") == "MTL"
    assert ask.find_team("Montreal") == "MTL"
    assert ask.find_team("Los Angeles Kings") == "LAK"
    assert ask.find_team("Maple Leaf") == "TOR"
    assert ask.find_team("how are the Bruins doing") == "BOS"
    assert ask.find_team("New York") is None   # two teams
    assert ask.find_team("Pastrnak") is None


def test_player_names():
    assert ask.find_players("david pastrnak", INDEX) == [INDEX[0]]
    assert ask.find_players("Pastrnak", INDEX) == [INDEX[0]]
    assert ask.find_players("stutzle", INDEX) == [INDEX[4]]           # no accent typed
    assert ask.find_players("pastranak", INDEX)[0] == INDEX[0]       # near spelling
    assert len(ask.find_players("Pettersson", INDEX)) == 2           # ask which
    assert ask.find_players("Nurse", INDEX) == []                    # PWHL isn't covered yet
    assert ask.find_players("zz", INDEX) == []


def test_plain_names_skip_the_model():
    assert ask.quick("Bruins", INDEX) == {"kind": "about", "names": ["bruins"]}
    assert ask.quick("Kings vs. Ducks?", INDEX) == {"kind": "about", "names": ["kings", "ducks"]}
    assert ask.quick("Pastrnak and Marner", INDEX)["names"] == ["pastrnak", "marner"]
    assert ask.quick("who leads in goals", INDEX) is None
    assert ask.quick("Bruins and Pastrnak", INDEX) is None   # one of each: let the model read it


def test_lang_literals():
    assert ask.c("Button", "Go", None, None) == 'Button("Go")'
    assert ask.c("X", None, "a") == 'X(null, "a")'
    assert ask.lit({"src": "/a", "n": 2}) == '{src: "/a", n: 2}'
    assert ask.lit('say "hi"\n') == r'"say \"hi\"\n"'
    assert ask.go("#/team/BOS") == '@OpenUrl("#/team/BOS")'


def test_one_team(no_model):
    lang, plan = run("Bruins")
    well_formed(lang)
    assert plan["kind"] == "about"
    assert 'CardHeader("Boston Bruins", "1st in the Atlantic · 7-3-1 · Streak W2")' in lang
    assert "W 4-2 vs Maple Leafs" in lang and "L 1-3 at Kings" in lang
    assert '@OpenUrl("#/team/BOS")' in lang
    assert "Pastrnak" in lang


def test_two_teams_head_to_head(no_model):
    no_model["leafs habs head to head"] = {"kind": "about", "names": ["Bruins", "Leafs"]}
    lang, _ = run("leafs habs head to head")
    well_formed(lang)
    assert "Bruins vs Maple Leafs" in lang and "Bruins 1-0 this season" in lang and "Next meeting" in lang


def test_players(no_model):
    lang, _ = run("Pastrnak")
    well_formed(lang)
    assert 'BoldText("number", "12")' in lang and "#/player/8477956" in lang
    lang, _ = run("pastrnak vs marner")
    well_formed(lang)
    assert "David Pastrnak vs Mitch Marner" in lang


def test_names_the_app_does_not_know(no_model):
    no_model["how is zzyzx doing"] = {"kind": "about", "names": ["zzyzx"]}
    lang, _ = run("how is zzyzx doing")
    assert "Couldn't find that" in lang and "zzyzx" in lang


def test_which_one(no_model):
    no_model["Pettersson"] = {"kind": "about", "names": ["Pettersson"]}
    lang, _ = run("Pettersson")
    assert "Which one?" in lang and lang.count('FollowUpItem("Elias Pettersson")') == 2


def test_leaders_standings_games(no_model):
    no_model["top goal scorers"] = {"kind": "leaders", "stat": "goals"}
    no_model["atlantic table"] = {"kind": "standings", "group": "atlantic"}
    no_model["scores last night"] = {"kind": "games", "day": "yesterday"}
    no_model["games"] = {"kind": "games"}
    for q, want in [("top goal scorers", "Goals leaders"), ("atlantic table", "Atlantic Division"),
                    ("scores last night", "TOR 2 - 4 BOS"), ("games", '"Live"')]:
        lang, _ = run(q)
        well_formed(lang)
        assert want in lang, q


def test_spoiler_free_hides_what_would_give_it_away(no_model):
    hidden = [{"id": 4, "league": "nhl", "state": "live", "away": {"abbr": "TOR"}, "home": {"abbr": "BOS"}}]
    assert "Spoiler-free is on" in run("Bruins", hidden)[0]
    assert "Spoiler-free is on" in run("Pastrnak", hidden)[0]
    no_model["standings"] = {"kind": "standings"}
    assert "Spoiler-free is on" in run("standings", hidden)[0]
    assert "Kings" in run("Kings", hidden)[0] and "Spoiler" not in run("Kings", hidden)[0]
    no_model["games"] = {"kind": "games"}
    sp = {"teams": ["BOS"], "games": [], "seen": []}
    lang, _ = run("games", hidden, sp)
    assert "Hidden (spoiler-free)" in lang and "TOR 1 - 2 BOS" not in lang


def test_model_down_or_nonsense(no_model, monkeypatch):
    no_model["what's the weather"] = {"kind": "weather", "names": [3], "stat": "speed"}
    lang, plan = run("what's the weather")
    assert plan == {"kind": "other", "names": [], "stat": None, "group": None, "day": None}
    assert "I can't answer that yet" in lang

    async def down(q):
        raise OSError("refused")
    monkeypatch.setattr(ask, "_ask_model", down)
    lang, plan = run("who is good")
    assert plan is None and "warming up" in lang
