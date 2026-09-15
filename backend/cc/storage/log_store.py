"""Keeps the server's log records in the database (table ``app_logs``), so they are copied to Supabase with the rest."""

from __future__ import annotations

import logging
import threading
import traceback

from ..data.models import now_ist
from .db import Database

SKIPPED_LOGGERS = ("uvicorn.access",)  # one line per HTTP request: far too many to keep


class DatabaseLogHandler(logging.Handler):
    """INFO and above from DalalSight's own ``cc`` loggers; WARNING and above from everything else."""

    def __init__(self, db: Database):
        super().__init__(logging.INFO)
        self.db = db
        self._local = threading.local()

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(SKIPPED_LOGGERS):
            return
        own = record.name == "cc" or record.name.startswith("cc.")
        if record.levelno < (logging.INFO if own else logging.WARNING):
            return
        if getattr(self._local, "busy", False):
            return  # a failure while storing a record must not log (and store) again
        self._local.busy = True
        try:
            detail = "".join(traceback.format_exception(*record.exc_info)) if record.exc_info else None
            self.db.execute(
                "INSERT INTO app_logs(ts, level, logger, message, detail) VALUES (?, ?, ?, ?, ?)",
                (now_ist().isoformat(), record.levelname, record.name[:120], record.getMessage()[:4000], detail[:20000] if detail else None),
            )
        except Exception:  # noqa: BLE001 — logging must never break the caller
            self.handleError(record)
        finally:
            self._local.busy = False
