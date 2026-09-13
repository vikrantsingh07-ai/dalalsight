"""Activity timeline and error log (persisted, broadcast to the dashboard)."""

from __future__ import annotations

import logging

from ..data.models import now_ist
from ..storage.db import Database, dumps, loads
from .bus import EventBus

log = logging.getLogger("cc")


class Timeline:
    def __init__(self, db: Database, bus: EventBus):
        self.db = db
        self.bus = bus

    def add(self, kind: str, message: str, symbol: str | None = None, payload: dict | None = None) -> dict:
        ts = now_ist().isoformat()
        entry_id = self.db.execute(
            "INSERT INTO timeline(ts, kind, symbol, message, payload) VALUES (?, ?, ?, ?, ?)",
            (ts, kind, symbol, message[:1000], dumps(payload or {})),
        )
        entry = {"id": entry_id, "ts": ts, "kind": kind, "symbol": symbol, "message": message, "payload": payload or {}}
        self.bus.publish("timeline", entry)
        return entry

    def recent(self, limit: int = 200, kind: str | None = None, symbol: str | None = None) -> list[dict]:
        clauses, params = [], []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.query(f"SELECT * FROM timeline {where} ORDER BY id DESC LIMIT ?", (*params, limit))
        for row in rows:
            row["payload"] = loads(row["payload"])
        return rows

    def error(self, source: str, message: str, detail: str | None = None, level: str = "ERROR") -> None:
        log.warning("%s: %s", source, message)
        ts = now_ist().isoformat()
        self.db.execute("INSERT INTO errors(ts, level, source, message, detail) VALUES (?, ?, ?, ?, ?)",
                        (ts, level, source, message[:500], (detail or "")[:4000]))
        self.bus.publish("error", {"ts": ts, "level": level, "source": source, "message": message})

    def errors(self, limit: int = 100) -> list[dict]:
        return self.db.query("SELECT * FROM errors ORDER BY id DESC LIMIT ?", (limit,))
