"""Copies the local database to Supabase (Postgres), so all of the software's data and logs are also kept in the cloud.

The local SQLite database stays the source of truth: the app keeps working without internet. Triggers
(``storage/db.py``) queue the key of every inserted, updated or deleted row in ``sync_outbox``; this worker reads the
current rows and upserts them through Supabase's REST API (PostgREST), or deletes rows that no longer exist locally.
A failed request leaves the queue untouched, so nothing is lost while offline.

Needs ``SUPABASE_URL`` and ``SUPABASE_SECRET_KEY``. The secret key bypasses row-level security, so it stays on the
server and is never logged or sent to the dashboard. The Supabase tables have RLS on and no public access.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from typing import Any

import requests

from ..config import EnvConfig
from ..data.models import now_ist
from ..storage.db import SYNC_TABLES, Database

log = logging.getLogger("cc.sync")

BATCH_KEYS = 500  # row keys handled per round
MAX_REQUEST_BYTES = 512_000  # rows are split into requests below this size
TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class Columns:
    json: frozenset[str] = frozenset()
    boolean: frozenset[str] = frozenset()


# Local TEXT columns holding JSON become jsonb; INTEGER 0/1 flags become boolean.
COLUMNS: dict[str, Columns] = {
    "settings": Columns(json=frozenset({"value"})),
    "watchlists": Columns(json=frozenset({"symbols"})),
    "scanners": Columns(json=frozenset({"definition"})),
    "signals": Columns(json=frozenset({"payload", "outcome"})),
    "commentary": Columns(json=frozenset({"payload"}), boolean=frozenset({"speak"})),
    "timeline": Columns(json=frozenset({"payload"})),
    "alerts": Columns(json=frozenset({"rule", "channels"}), boolean=frozenset({"enabled"})),
    "alert_events": Columns(json=frozenset({"payload", "delivery"})),
    "agent_runs": Columns(json=frozenset({"results", "consensus"})),
    "chat_messages": Columns(json=frozenset({"payload"})),
    "backtests": Columns(json=frozenset({"params", "summary", "trades"})),
    "option_snapshots": Columns(json=frozenset({"summary"})),
}


class SyncError(RuntimeError):
    pass


def supabase_headers(key: str, prefer: str | None = None) -> dict[str, str]:
    """New ``sb_secret_`` keys go only in the apikey header; a legacy service_role JWT also goes in Authorization."""
    headers = {"apikey": key, "Accept": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    if prefer:
        headers["Prefer"] = prefer
        headers["Content-Type"] = "application/json"
    return headers


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text  # kept as a JSON string rather than lost


def convert(table: str, row: dict) -> dict:
    spec = COLUMNS.get(table, Columns())
    out: dict[str, Any] = {}
    for name, value in row.items():
        if name in spec.json and isinstance(value, str):
            value = _parse_json(value)
        elif name in spec.boolean and value is not None:
            value = bool(value)
        out[name] = value
    return out


class SupabaseSync:
    def __init__(self, env: EnvConfig, db: Database, session: Any = None):
        self.env = env
        self.db = db
        self.url = env.supabase_url.rstrip("/")
        self.session = session or requests.Session()
        self._lock = threading.Lock()
        self.last_success: str | None = None
        self.last_error: str | None = None
        self.rows_sent = 0
        self.rows_deleted = 0

    @property
    def configured(self) -> bool:
        return bool(self.env.supabase_url and self.env.supabase_secret_key)

    def pending(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM (SELECT DISTINCT tbl, pk FROM sync_outbox)")
        return int(row["n"]) if row else 0

    def status(self) -> dict:
        return {
            "configured": self.configured,
            "pending": self.pending(),
            "last_success": self.last_success,
            "last_error": self.last_error,
            "rows_sent": self.rows_sent,
            "rows_deleted": self.rows_deleted,
            "interval_seconds": self.env.supabase_sync_seconds,
        }

    async def run(self) -> None:
        while True:
            await asyncio.to_thread(self.drain)
            await asyncio.sleep(max(5, self.env.supabase_sync_seconds))

    def drain(self) -> None:
        """Send everything queued. Errors are recorded (and logged once per failure streak); the queue is kept."""
        if not self.configured:
            return
        try:
            while self.sync_once() >= BATCH_KEYS:
                pass
        except (requests.RequestException, SyncError, ValueError) as exc:
            if self.last_error is None:
                log.warning("Supabase sync paused, changes stay queued: %s", exc)
            self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            return
        if self.last_error is not None:
            log.info("Supabase sync resumed")
        self.last_error = None
        self.last_success = now_ist().isoformat()

    def sync_once(self) -> int:
        """Send one round of queued changes; returns how many row keys it handled."""
        with self._lock:
            top = self.db.query_one("SELECT MAX(seq) AS seq FROM sync_outbox")
            if not top or top["seq"] is None:
                return 0
            keys = self.db.query(
                "SELECT tbl, pk, MAX(seq) AS seq FROM sync_outbox WHERE seq <= ? GROUP BY tbl, pk ORDER BY MIN(seq) LIMIT ?",
                (top["seq"], BATCH_KEYS),
            )
            by_table: dict[str, list[dict]] = {}
            for key in keys:
                by_table.setdefault(key["tbl"], []).append(key)
            for table, entries in by_table.items():
                pk = SYNC_TABLES.get(table)
                if pk is not None:
                    values = [str(entry["pk"]) for entry in entries]
                    rows = self.db.query(f"SELECT * FROM {table} WHERE {pk} IN ({', '.join('?' for _ in values)})", tuple(values))
                    present = {str(row[pk]) for row in rows}
                    self._upsert(table, pk, [convert(table, row) for row in rows])
                    gone = [value for value in values if value not in present]
                    if gone:
                        self._delete(table, pk, gone)
                for entry in entries:
                    self.db.execute("DELETE FROM sync_outbox WHERE tbl = ? AND pk = ? AND seq <= ?", (entry["tbl"], entry["pk"], entry["seq"]))
            return len(keys)

    def _upsert(self, table: str, pk: str, rows: list[dict]) -> None:
        chunk: list[str] = []
        size = 0
        for row in rows:
            encoded = json.dumps(row, default=str, allow_nan=False)
            if chunk and size + len(encoded) > MAX_REQUEST_BYTES:
                self._post(table, pk, chunk)
                chunk, size = [], 0
            chunk.append(encoded)
            size += len(encoded) + 1
        if chunk:
            self._post(table, pk, chunk)

    def _post(self, table: str, pk: str, encoded_rows: list[str]) -> None:
        response = self.session.post(
            f"{self.url}/rest/v1/{table}",
            params={"on_conflict": pk},
            data=f"[{','.join(encoded_rows)}]".encode(),
            headers=supabase_headers(self.env.supabase_secret_key, "resolution=merge-duplicates,return=minimal"),
            timeout=TIMEOUT_SECONDS,
        )
        self._check(response, f"saving {len(encoded_rows)} {table} row(s)")
        self.rows_sent += len(encoded_rows)

    def _delete(self, table: str, pk: str, values: list[str]) -> None:
        quoted = ",".join('"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"' for value in values)
        response = self.session.delete(
            f"{self.url}/rest/v1/{table}",
            params={pk: f"in.({quoted})"},
            headers=supabase_headers(self.env.supabase_secret_key, "return=minimal"),
            timeout=TIMEOUT_SECONDS,
        )
        self._check(response, f"deleting {len(values)} {table} row(s)")
        self.rows_deleted += len(values)

    @staticmethod
    def _check(response: Any, what: str) -> None:
        if response.status_code >= 300:
            raise SyncError(f"{what}: HTTP {response.status_code} {str(response.text)[:300]}")
