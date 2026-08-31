"""SQLite persistence — tracks every seen company/post so alerts never repeat."""
import json
import sqlite3
import threading
import time
from pathlib import Path

from config import DB_PATH

_lock = threading.Lock()

def _conn():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS seen (
        kind TEXT NOT NULL,          -- 'company' | 'launch' | 'social_post'
        uid TEXT NOT NULL,           -- slug/id/post-id
        first_seen REAL NOT NULL,
        payload TEXT,
        alerted INTEGER DEFAULT 0,
        PRIMARY KEY (kind, uid))""")
    c.execute("""CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        kind TEXT NOT NULL,          -- 'early' | 'official' | 'speedrun'
        title TEXT, body TEXT, link TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS meta (
        k TEXT PRIMARY KEY, v TEXT)""")
    return c

def is_seen(kind: str, uid: str) -> bool:
    with _lock, _conn() as c:
        row = c.execute("SELECT 1 FROM seen WHERE kind=? AND uid=?", (kind, uid)).fetchone()
        return row is not None

def mark_seen(kind: str, uid: str, payload: dict | None = None, alerted: bool = False):
    with _lock, _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO seen (kind, uid, first_seen, payload, alerted) VALUES (?,?,?,?,?)",
            (kind, uid, time.time(), json.dumps(payload or {}), int(alerted)))

def mark_alerted(kind: str, uid: str):
    with _lock, _conn() as c:
        c.execute("UPDATE seen SET alerted=1 WHERE kind=? AND uid=?", (kind, uid))

def record_alert(kind: str, title: str, body: str, link: str):
    with _lock, _conn() as c:
        c.execute("INSERT INTO alerts (ts, kind, title, body, link) VALUES (?,?,?,?,?)",
                  (time.time(), kind, title, body, link))

def count(kind: str) -> int:
    with _lock, _conn() as c:
        return c.execute("SELECT COUNT(*) FROM seen WHERE kind=?", (kind,)).fetchone()[0]

def alert_count() -> int:
    with _lock, _conn() as c:
        return c.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]

def last_alert_time() -> float | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT MAX(ts) FROM alerts").fetchone()
        return row[0] if row and row[0] else None

def set_meta(k: str, v: str):
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?,?)", (k, v))

def get_meta(k: str) -> str | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return row[0] if row else None

def recent_alerts(limit: int = 20) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT ts, kind, title, body, link FROM alerts ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    return [{"ts": r[0], "kind": r[1], "title": r[2], "body": r[3], "link": r[4]} for r in rows]
