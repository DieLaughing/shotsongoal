"""The server's side of team colours, first-run setup and recaps."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sog import feed, nhl
from test_core import as_user, client  # noqa: F401  (the app fixture)

FIX = Path(__file__).parent / "fixtures"


def test_settings_keep_the_accent_and_leave_unanswered_services_alone(client, monkeypatch):  # noqa: F811
    as_user(monkeypatch, "owner@x.com")
    s = client.put("/api/settings", json={"accent": "BOS", "welcomed": True}).json()
    assert s["accent"] == "BOS" and s["welcomed"] is True
    assert "services" not in s    # skipping setup isn't the same as having no services
    assert client.put("/api/settings", json={"accent": "<script>"}).json()["accent"] == ""
    s = client.put("/api/settings", json={"accent": "none", "services": []}).json()
    assert s["accent"] == "none" and s["services"] == []


def test_recap_ids_come_from_the_right_rail():
    landing = json.loads((FIX / "landing_final.json").read_text())
    d = nhl.parse_detail(landing, {"gameVideo": {"threeMinRecap": 11, "condensedGame": 22}}, None)
    assert d["video"] == {"recap": 11, "condensed": 22}
    assert nhl.parse_detail(landing, None, None)["video"] == {"recap": None, "condensed": None}


def test_a_final_keeps_looking_for_its_recap_for_two_days():
    def ttl(hours, video):
        start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
        detail = {"game": {"state": "final", "start": start}}
        return feed._game_ttl({**detail, "video": video} if video is not None else detail)
    missing, have = {"recap": None, "condensed": None}, {"recap": 1, "condensed": 2}
    assert ttl(2, have) == timedelta(minutes=10)      # settling
    assert ttl(12, have) is None                      # history
    assert ttl(12, missing) == timedelta(minutes=30)  # the recap may still come
    assert ttl(60, missing) is None                   # it isn't coming
    assert ttl(12, None) is None                      # PWHL and college have none to wait for
