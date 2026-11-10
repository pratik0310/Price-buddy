"""Tiny SQLite cache so same product is not searched twice (saves API quota)."""
import json
import sqlite3
import time

DB_PATH = "cache.db"
TTL_SECONDS = 6 * 60 * 60  # 6 hours


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cache (q TEXT PRIMARY KEY, data TEXT, ts INTEGER)"
    )
    return conn


def get(query: str):
    key = query.strip().lower()
    with _conn() as conn:
        row = conn.execute("SELECT data, ts FROM cache WHERE q = ?", (key,)).fetchone()
    if not row:
        return None
    data, ts = row
    if time.time() - ts > TTL_SECONDS:
        return None
    return json.loads(data)


def put(query: str, data) -> None:
    key = query.strip().lower()
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache (q, data, ts) VALUES (?, ?, ?)",
            (key, json.dumps(data), int(time.time())),
        )