import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.environ.get("SPACENOTIFIER_DB", "/data/spacenotifier.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS launches (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    net_utc TEXT NOT NULL,
    status TEXT,
    notified INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""


@contextmanager
def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def get_setting(key: str, default: str | None = None) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def upsert_launch(launch_id: str, name: str, net_utc: str, status: str | None) -> bool:
    """Insert or update a launch. Returns True if net_utc changed (so caller can reschedule)."""
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        existing = conn.execute(
            "SELECT net_utc, notified FROM launches WHERE id = ?", (launch_id,)
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO launches(id, name, net_utc, status, notified, updated_at) "
                "VALUES(?, ?, ?, ?, 0, ?)",
                (launch_id, name, net_utc, status, now),
            )
            return True
        net_changed = existing["net_utc"] != net_utc
        conn.execute(
            "UPDATE launches SET name = ?, net_utc = ?, status = ?, updated_at = ? "
            "WHERE id = ?",
            (name, net_utc, status, now, launch_id),
        )
        # If net moved and we already notified, we leave notified=1 — we don't
        # re-notify the same launch for a scrub/slip in MVP.
        return net_changed and existing["notified"] == 0


def mark_notified(launch_id: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE launches SET notified = 1 WHERE id = ?", (launch_id,))


def get_pending_launches() -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                "SELECT id, name, net_utc, status FROM launches "
                "WHERE notified = 0 ORDER BY net_utc ASC"
            )
        )


def list_upcoming_launches(limit: int = 5) -> list[sqlite3.Row]:
    """Launches whose T-0 is still in the future."""
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        return list(
            conn.execute(
                "SELECT id, name, net_utc, status, notified FROM launches "
                "WHERE net_utc >= ? ORDER BY net_utc ASC LIMIT ?",
                (now, limit),
            )
        )


def delete_past_launches() -> int:
    """Delete launches whose T-0 is already in the past. Returns rows deleted."""
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        cur = conn.execute("DELETE FROM launches WHERE net_utc < ?", (now,))
        return cur.rowcount
