"""Showcase games (Winter Classic, Stadium Series, Global Series): naming, slates, weather at puck drop."""
import asyncio
from datetime import datetime, timedelta, timezone

from sog import nhl, weather
from sog.db import Store
from sog.feed import Feed


def ev(name, neutral=None, city=None):
    return {"specialEvent": {"name": {"default": name}}, "neutralSite": neutral,
            "venueLocation": {"default": city} if city else None}


def test_event_names_and_kinds():
    assert nhl.parse_event(ev("Discover NHL Winter Classic", True, "Salt Lake City")) == {
        "name": "Winter Classic", "kind": "outdoor", "city": "Salt Lake City"}
    assert nhl.parse_event(ev("2027 Navy Federal Credit Union NHL Stadium Series", True))["name"] == "Stadium Series"
    assert nhl.parse_event(ev("2026 NHL Global Series", None, "Düsseldorf"))["kind"] == "global"   # game pages lack neutralSite
    assert nhl.parse_event(ev("Original 6 Series", False)) is None    # a marketing tag on an ordinary home game
    assert nhl.parse_event({"specialEvent": None}) is None


def test_scoreboard_games_get_their_event_from_saved_team_schedules(tmp_path):
    feed = Feed(Store(tmp_path / "t.db"))
    wc = {"name": "Winter Classic", "kind": "outdoor", "city": "Salt Lake City"}
    feed.store.put("team:UTA:schedule", [{"id": 1, "event": wc}, {"id": 2, "event": None}], timedelta(minutes=30))
    feed.store.put("evcity:9", "Düsseldorf", timedelta(days=30))
    feed.store.put("team:CHI:schedule", [{"id": 9, "event": {"name": "Global Series", "kind": "global", "city": None}}],
                   timedelta(minutes=30))
    games = feed.with_events([{"id": 1}, {"id": 2}, {"id": 3}])
    assert games[0]["event"] == wc and "event" not in games[1] and "event" not in games[2]
    assert feed.with_events([{"id": 9}])[0]["event"]["city"] == "Düsseldorf"   # the city read once from the game's page


def test_weather_only_for_outdoor_games_within_a_week():
    now = datetime(2026, 12, 28, 12, tzinfo=timezone.utc)
    g = {"event": {"kind": "outdoor", "city": "Salt Lake City"}, "start": "2026-12-31T23:00:00Z", "state": "pre"}
    assert weather.wanted(g, now)
    assert not weather.wanted({**g, "start": "2027-01-10T23:00:00Z"}, now)       # too far out to forecast
    assert not weather.wanted({**g, "state": "final"}, now)
    assert not weather.wanted({**g, "event": {"kind": "stadium", "city": "Arlington"}}, now)   # under a roof
    assert not weather.wanted({**g, "event": None}, now)


def test_forecast_is_the_hour_of_puck_drop(monkeypatch):
    times = [f"2026-12-31T{h:02d}:00" for h in range(24)]

    async def fake_get(url, params):
        return {"hourly": {"time": times, "temperature_2m": [float(h) - 10 for h in range(24)],
                           "weather_code": [71] * 24, "wind_speed_10m": [12.0] * 24}}
    monkeypatch.setattr(weather, "_get", fake_get)
    wx = asyncio.run(weather.forecast(40.76, -111.85, "2026-12-31T23:30:00Z"))
    assert wx == {"c": 13.0, "code": 71, "text": "light snow", "wind": 12.0}
