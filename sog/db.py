"""SQLite storage: the saved copy of NHL data, plus who is allowed in."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY, data TEXT NOT NULL, fetched TEXT NOT NULL, expires TEXT  -- expires NULL = keep forever
);
CREATE TABLE IF NOT EXISTS source_run (
    source TEXT PRIMARY KEY, last_try TEXT, last_ok TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS user (
    email TEXT PRIMARY KEY,
    status TEXT NOT NULL,          -- pending | approved | denied | revoked
    requested TEXT, decided TEXT,
    nonce TEXT,                    -- makes each Approve/Deny link single-use
    settings TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS insider (
    handle TEXT PRIMARY KEY, label TEXT NOT NULL, added TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS push_sub (
    endpoint TEXT PRIMARY KEY, email TEXT NOT NULL, sub TEXT NOT NULL, created TEXT NOT NULL, agent TEXT
);
CREATE TABLE IF NOT EXISTS sent (       -- alerts already pushed (or deliberately skipped), so none repeat
    key TEXT PRIMARY KEY, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS report (     -- "wrong channel?" reports from game pages
    id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, game_id INTEGER NOT NULL, game TEXT,
    shown TEXT, note TEXT, created TEXT NOT NULL, resolved TEXT
);
CREATE TABLE IF NOT EXISTS invite (   -- used_by/used_at: single-use invites from before invite_use
    code TEXT PRIMARY KEY, created TEXT NOT NULL, note TEXT, used_by TEXT, used_at TEXT,
    max_uses INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS invite_use (
    code TEXT NOT NULL, email TEXT NOT NULL, used_at TEXT NOT NULL, PRIMARY KEY (code, email)
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        # WAL + NORMAL: a save doesn't wait for the disk to confirm it (on a USB drive that's up to ~400 ms, and saves
        # run on the worker that answers requests). A power cut can lose the last moment of saves; nothing corrupts.
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        if "league" not in [r[1] for r in self.conn.execute("PRAGMA table_info(insider)")]:
            self.conn.execute("ALTER TABLE insider ADD COLUMN league TEXT NOT NULL DEFAULT 'nhl'")
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(user)")]
        if "cal_token" not in cols:  # databases from before calendar feeds
            self.conn.execute("ALTER TABLE user ADD COLUMN cal_token TEXT")
        if "max_uses" not in [r[1] for r in self.conn.execute("PRAGMA table_info(invite)")]:  # before multi-use invites
            with self.conn:
                self.conn.execute("ALTER TABLE invite ADD COLUMN max_uses INTEGER NOT NULL DEFAULT 1")
                self.conn.execute("INSERT OR IGNORE INTO invite_use (code, email, used_at) "
                                  "SELECT code, used_by, used_at FROM invite WHERE used_by IS NOT NULL")
        self.lock = threading.Lock()
        self._held = 0  # open batch() blocks: saves wait for one commit at the end
        self.path = path
        self._ckpt: sqlite3.Connection | None = None

    # ---- saved copy ---------------------------------------------------------
    def get(self, key: str) -> dict | None:
        row = self.conn.execute("SELECT data, fetched, expires FROM cache WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        fresh = row["expires"] is None or parse_iso(row["expires"]) > datetime.now(timezone.utc)
        return {"data": json.loads(row["data"]), "fetched": row["fetched"], "fresh": fresh}

    def meta(self, key: str) -> tuple[str, str | None, bool] | None:
        """(fetched, expires, fresh) for a saved copy, without reading or parsing the data itself."""
        row = self.conn.execute("SELECT fetched, expires FROM cache WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        return row["fetched"], row["expires"], row["expires"] is None or parse_iso(row["expires"]) > datetime.now(timezone.utc)

    def put(self, key: str, data, ttl: timedelta | None) -> None:
        expires = (datetime.now(timezone.utc) + ttl).strftime("%Y-%m-%dT%H:%M:%SZ") if ttl else None
        text = json.dumps(data, separators=(",", ":"))
        self._write(lambda: self.conn.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?,?)", (key, text, now_iso(), expires)))

    # ---- checkpoints off the request path ------------------------------------------------------
    def manual_checkpoints(self) -> None:
        """Stop SQLite folding the WAL back into the database inside whichever save happens to trigger it (on a USB
        drive that save could wait hundreds of ms). The poller calls checkpoint() between passes instead."""
        self.conn.execute("PRAGMA wal_autocheckpoint=0")

    def checkpoint(self) -> tuple[int, int, int]:
        """A PASSIVE checkpoint on its own connection: never blocks readers or writers. Run it in a thread."""
        if self._ckpt is None:
            self._ckpt = sqlite3.connect(self.path, check_same_thread=False)
        return tuple(self._ckpt.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone())

    # ---- group commit ------------------------------------------------------------------------
    @contextmanager
    def batch(self):
        """Hold the commits of a burst of background saves and make them one (a single disk sync for the lot).
        Anyone else's commit in the meantime simply takes the held saves with it."""
        self._held += 1
        try:
            yield
        finally:
            self._held -= 1
            if not self._held:
                with self.lock:
                    self.conn.commit()

    def _write(self, do) -> None:
        with self.lock:
            if self._held:
                do()
            else:
                with self.conn:
                    do()

    def record_run(self, source: str, ok: bool, error: str | None = None) -> None:
        now = now_iso()

        def do():
            self.conn.execute("INSERT OR IGNORE INTO source_run (source) VALUES (?)", (source,))
            if ok:
                self.conn.execute("UPDATE source_run SET last_try=?, last_ok=?, error=NULL WHERE source=?",
                                  (now, now, source))
            else:
                self.conn.execute("UPDATE source_run SET last_try=?, error=? WHERE source=?", (now, error, source))
        self._write(do)

    def runs(self) -> dict[str, dict]:
        return {r["source"]: dict(r) for r in self.conn.execute("SELECT * FROM source_run ORDER BY source")}

    # ---- people ---------------------------------------------------------------
    def user(self, email: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM user WHERE email=?", (email,)).fetchone()
        if not row:
            return None
        return {**dict(row), "settings": json.loads(row["settings"])}

    def users(self) -> list[dict]:
        return [{**dict(r), "settings": json.loads(r["settings"])}
                for r in self.conn.execute("SELECT * FROM user ORDER BY status, requested DESC")]

    def set_status(self, email: str, status: str, nonce: str | None = None) -> None:
        now = now_iso()
        with self.lock, self.conn:
            self.conn.execute("INSERT OR IGNORE INTO user (email, status) VALUES (?, ?)", (email, status))
            if status == "pending":
                self.conn.execute("UPDATE user SET status=?, requested=?, decided=NULL, nonce=? WHERE email=?",
                                  (status, now, nonce, email))
            else:
                self.conn.execute("UPDATE user SET status=?, decided=?, nonce=NULL WHERE email=?",
                                  (status, now, email))

    def save_settings(self, email: str, settings: dict) -> None:
        with self.lock, self.conn:
            self.conn.execute("UPDATE user SET settings=? WHERE email=?", (json.dumps(settings), email))

    def cal_token(self, email: str, make) -> str:
        row = self.conn.execute("SELECT cal_token FROM user WHERE email=?", (email,)).fetchone()
        if row and row["cal_token"]:
            return row["cal_token"]
        token = make()
        with self.lock, self.conn:
            self.conn.execute("UPDATE user SET cal_token=? WHERE email=?", (token, email))
        return token

    def user_by_cal_token(self, token: str) -> dict | None:
        row = self.conn.execute("SELECT email FROM user WHERE cal_token=?", (token,)).fetchone()
        return self.user(row["email"]) if row else None

    # ---- insiders (the Bluesky list) ---------------------------------------------------
    def insiders(self, defaults: dict[str, list[tuple[str, str]]] | None = None) -> list[dict]:
        """The Bluesky list. Each league's starter list is added the first time that league has no accounts."""
        for league, rows in (defaults or {}).items():
            if not self.conn.execute("SELECT 1 FROM insider WHERE league=? LIMIT 1", (league,)).fetchone():
                with self.lock, self.conn:
                    self.conn.executemany("INSERT OR IGNORE INTO insider (handle, label, added, league) VALUES (?,?,?,?)",
                                          [(h, label, now_iso(), league) for h, label in rows])
        return [dict(r) for r in self.conn.execute("SELECT * FROM insider ORDER BY league, label COLLATE NOCASE")]

    def add_insider(self, handle: str, label: str, league: str = "nhl") -> None:
        with self.lock, self.conn:
            self.conn.execute("INSERT OR REPLACE INTO insider (handle, label, added, league) VALUES (?,?,?,?)",
                              (handle, label, now_iso(), league))

    def remove_insider(self, handle: str) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM insider WHERE handle=?", (handle,))

    # ---- push subscriptions and sent alerts -----------------------------------------------
    def add_push(self, email: str, sub: dict, agent: str | None) -> None:
        with self.lock, self.conn:
            self.conn.execute("INSERT OR REPLACE INTO push_sub VALUES (?,?,?,?,?)",
                              (sub["endpoint"], email, json.dumps(sub), now_iso(), (agent or "")[:200]))

    def remove_push(self, endpoint: str, email: str | None = None) -> None:
        with self.lock, self.conn:
            if email:
                self.conn.execute("DELETE FROM push_sub WHERE endpoint=? AND email=?", (endpoint, email))
            else:
                self.conn.execute("DELETE FROM push_sub WHERE endpoint=?", (endpoint,))

    def pushes(self, email: str | None = None) -> list[dict]:
        """Subscriptions of approved people (one person, or everyone)."""
        q = "SELECT p.* FROM push_sub p JOIN user u ON u.email=p.email WHERE u.status='approved'"
        rows = self.conn.execute(q + (" AND p.email=?" if email else ""), (email,) if email else ())
        return [{**dict(r), "sub": json.loads(r["sub"])} for r in rows]

    def was_sent(self, key: str) -> bool:
        return self.conn.execute("SELECT 1 FROM sent WHERE key=?", (key,)).fetchone() is not None

    def mark_sent(self, keys: list[str]) -> None:
        now = now_iso()
        with self.lock, self.conn:
            self.conn.executemany("INSERT OR IGNORE INTO sent VALUES (?,?)", [(k, now) for k in keys])
            # Keep the table small: nothing older than two weeks can come round again.
            self.conn.execute("DELETE FROM sent WHERE at < ?",
                              ((datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ"),))

    # ---- channel reports --------------------------------------------------------------------
    def add_report(self, email: str, game_id: int, game: str, shown: str, note: str) -> None:
        with self.lock, self.conn:
            self.conn.execute("INSERT INTO report (email, game_id, game, shown, note, created) VALUES (?,?,?,?,?,?)",
                              (email, game_id, game, shown, note, now_iso()))

    def reports(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM report ORDER BY resolved IS NOT NULL, created DESC LIMIT 50")]

    def resolve_report(self, rid: int) -> None:
        with self.lock, self.conn:
            self.conn.execute("UPDATE report SET resolved=? WHERE id=?", (now_iso(), rid))

    def add_invite(self, code: str, note: str | None, max_uses: int = 1) -> None:
        with self.lock, self.conn:
            self.conn.execute("INSERT INTO invite (code, created, note, max_uses) VALUES (?,?,?,?)",
                              (code, now_iso(), note, max_uses))

    def invite(self, code: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM invite WHERE code=?", (code,)).fetchone()
        if not row:
            return None
        uses = [dict(r) for r in self.conn.execute(
            "SELECT email, used_at FROM invite_use WHERE code=? ORDER BY used_at", (code,))]
        return {k: row[k] for k in ("code", "created", "note", "max_uses")} | {"uses": uses}

    def use_invite(self, code: str, email: str) -> bool:
        """Records this email on an invite with room left. False if it doesn't exist, is full, or they already used it."""
        with self.lock, self.conn:
            row = self.conn.execute("SELECT max_uses FROM invite WHERE code=?", (code,)).fetchone()
            if not row:
                return False
            used = self.conn.execute("SELECT COUNT(*) FROM invite_use WHERE code=?", (code,)).fetchone()[0]
            if used >= row["max_uses"]:
                return False
            cur = self.conn.execute("INSERT OR IGNORE INTO invite_use (code, email, used_at) VALUES (?,?,?)",
                                    (code, email, now_iso()))
            return cur.rowcount == 1

    def invites(self) -> list[dict]:
        codes = [r[0] for r in self.conn.execute("SELECT code FROM invite ORDER BY created DESC")]
        return [self.invite(c) for c in codes]

    def delete_invite(self, code: str) -> None:
        """Deletes an unused invite; one somebody joined with is closed instead, so it still shows who used it."""
        with self.lock, self.conn:
            used = self.conn.execute("SELECT COUNT(*) FROM invite_use WHERE code=?", (code,)).fetchone()[0]
            if used:
                self.conn.execute("UPDATE invite SET max_uses=? WHERE code=?", (used, code))
            else:
                self.conn.execute("DELETE FROM invite WHERE code=?", (code,))
