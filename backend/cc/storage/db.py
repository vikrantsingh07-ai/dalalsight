"""SQLite storage with simple versioned migrations.

One connection guarded by a re-entrant lock: the app is a single-user local process, and
SQLite in WAL mode handles the background workers' writes comfortably.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

MIGRATIONS: list[str] = [
    """
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE watchlists (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, symbols TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE scanners (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, definition TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, source TEXT NOT NULL,
        symbol TEXT NOT NULL, timeframe TEXT NOT NULL, bar_time TEXT NOT NULL, label TEXT NOT NULL,
        direction INTEGER NOT NULL, price REAL, bullish_pct REAL, confidence REAL, coverage REAL,
        entry_low REAL, entry_high REAL, stop REAL, target1 REAL, target2 REAL, rr REAL,
        payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', outcome TEXT, closed_at TEXT);
    CREATE INDEX idx_signals_symbol ON signals(symbol, timeframe, created_at);
    CREATE TABLE commentary (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
        priority TEXT NOT NULL, text TEXT NOT NULL, text_source TEXT NOT NULL, speak INTEGER NOT NULL,
        mode TEXT NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE timeline (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, kind TEXT NOT NULL, symbol TEXT,
        message TEXT NOT NULL, payload TEXT NOT NULL);
    CREATE INDEX idx_timeline_ts ON timeline(ts);
    CREATE TABLE alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, rule TEXT NOT NULL, channels TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1, cooldown_seconds INTEGER NOT NULL DEFAULT 900,
        created_at TEXT NOT NULL, last_triggered_at TEXT);
    CREATE TABLE alert_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, alert_id INTEGER, ts TEXT NOT NULL, symbol TEXT,
        message TEXT NOT NULL, payload TEXT NOT NULL, delivery TEXT NOT NULL);
    CREATE TABLE agent_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT, kind TEXT NOT NULL,
        symbol TEXT NOT NULL, timeframe TEXT NOT NULL, status TEXT NOT NULL, model TEXT,
        results TEXT, consensus TEXT, error TEXT);
    CREATE TABLE llm_usage (day TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE paper_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, symbol TEXT NOT NULL, instrument TEXT NOT NULL,
        side TEXT NOT NULL, quantity REAL NOT NULL, price REAL NOT NULL, price_source TEXT NOT NULL,
        status TEXT NOT NULL, note TEXT);
    CREATE TABLE errors (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, level TEXT NOT NULL, source TEXT NOT NULL,
        message TEXT NOT NULL, detail TEXT);
    CREATE TABLE chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, session TEXT NOT NULL, role TEXT NOT NULL,
        content TEXT NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE backtests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, status TEXT NOT NULL,
        params TEXT NOT NULL, summary TEXT, trades TEXT, error TEXT);
    CREATE TABLE option_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, symbol TEXT NOT NULL, expiry TEXT NOT NULL,
        summary TEXT NOT NULL);
    """,
]


def _default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return str(value)


def dumps(value: Any) -> str:
    return json.dumps(value, default=_default, allow_nan=False, separators=(",", ":"))


def loads(value: str | None) -> Any:
    return json.loads(value) if value else None


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    def migrate(self) -> None:
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            for index, script in enumerate(MIGRATIONS[version:], start=version + 1):
                self._conn.executescript(f"BEGIN; {script}; PRAGMA user_version={index}; COMMIT;")

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        """INSERT returns the new row id; every other statement returns the number of affected rows."""
        with self._lock:
            cursor = self._conn.execute(sql, params)
            if sql.lstrip().upper().startswith("INSERT"):
                return int(cursor.lastrowid or 0)
            return max(int(cursor.rowcount), 0)

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def query_one(self, sql: str, params: tuple | dict = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def ping(self) -> bool:
        try:
            with self._lock:
                self._conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def close(self) -> None:
        with self._lock:
            self._conn.close()
