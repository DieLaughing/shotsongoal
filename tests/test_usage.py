"""Page views: anonymous counts per page and day, the owner's own views left out, old days dropped."""
import sqlite3

from sog import usage
from test_core import as_user, client  # noqa: F401  (the app fixture)


def _setup():
    usage.init(sqlite3.connect(":memory:", check_same_thread=False))
    usage._cleaned = None


def test_batches_add_up_and_bad_keys_are_dropped():
    _setup()
    assert usage.add({"tonight": 3, "game/:id": 2}, "a", day="2026-10-16") == 5
    assert usage.add({"tonight": 1, "Bad Route": 4, "wire": -2, "picks": True, "league": "x",
                      "game/:id": 10_000}, "a", day="2026-10-16") == 1 + usage.MAX_VIEWS
    rows = {r["route"]: r["views"] for r in usage.days()}
    assert rows == {"tonight": 4, "game/:id": 2 + usage.MAX_VIEWS}


def test_summary_windows_and_cleanup():
    _setup()
    usage.add({"wire": 2}, "a", day="2026-09-20")
    usage.add({"tonight": 1, "wire": 1}, "a", day="2026-10-14")
    usage._conn.execute("INSERT INTO page_view VALUES ('2026-04-18', 'wire', 5)")   # the last kept day on 10-15, gone on 10-16
    s = usage.summary(day="2026-10-15")      # April 18 = exactly KEEP_DAYS back: still kept
    assert [p["route"] for p in s["pages"]] == ["wire", "tonight"]
    assert s["pages"][0] == {"route": "wire", "week": 1, "month": 3, "all": 8}
    assert usage.summary(day="2026-10-16")["first"] == "2026-09-20"   # reading drops anything past KEEP_DAYS


def test_views_endpoint_skips_the_owner(client, monkeypatch):  # noqa: F811
    as_user(monkeypatch, "owner@x.com")
    client.post("/api/admin/users", json={"email": "fan@x.com", "status": "approved"})
    assert client.post("/api/views", json={"views": {"tonight": 2}}).status_code == 204
    assert client.get("/api/admin/usage").json()["days"] == []
    as_user(monkeypatch, "fan@x.com")
    assert client.post("/api/views", json={"views": {"tonight": 2, "wire": 1}}).status_code == 204
    assert client.post("/api/views", content=b"not json").status_code == 400
    assert client.get("/api/admin/usage").status_code == 403
    as_user(monkeypatch, "owner@x.com")
    assert {r["route"]: r["views"] for r in client.get("/api/admin/usage").json()["days"]} == {"tonight": 2, "wire": 1}
    assert client.get("/api/admin").json()["usage"]["pages"][0]["route"] == "tonight"
    assert client.get("/api/admin/usage?since=nope").status_code == 400


def test_one_person_cant_flood_a_day():
    _setup()
    for _ in range(usage.PER_DAY // usage.MAX_VIEWS + 5):
        usage.add({"wire": 10_000}, "loop", day="2026-10-16")
    usage.add({"tonight": 1}, "friend", day="2026-10-16")
    assert {r["route"]: r["views"] for r in usage.days("2026-10-16")} == {"wire": usage.PER_DAY, "tonight": 1}
    assert usage.add({"wire": 5}, "loop", day="2026-10-17") == 5   # a new day, a new allowance
