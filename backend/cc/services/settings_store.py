"""Persisted, validated runtime settings."""

from __future__ import annotations

import threading
from collections.abc import Callable

from pydantic import ValidationError

from ..config import RuntimeSettings, deep_merge
from ..data.models import now_ist
from ..storage.db import Database, dumps, loads


class SettingsStore:
    KEY = "runtime"

    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.Lock()
        self._listeners: list[Callable[[RuntimeSettings], None]] = []
        self.load_error: str | None = None
        row = db.query_one("SELECT value FROM settings WHERE key = ?", (self.KEY,))
        try:
            self._settings = RuntimeSettings.model_validate(loads(row["value"])) if row else RuntimeSettings()
        except ValidationError as exc:
            self._settings = RuntimeSettings()
            self.load_error = f"stored settings were invalid and defaults were loaded: {exc.errors()[0]['msg']}"

    def get(self) -> RuntimeSettings:
        return self._settings

    def on_change(self, listener: Callable[[RuntimeSettings], None]) -> None:
        self._listeners.append(listener)

    def update(self, patch: dict) -> RuntimeSettings:
        with self._lock:
            merged = deep_merge(self._settings.model_dump(), patch)
            settings = RuntimeSettings.model_validate(merged)  # raises ValidationError on bad input
            self.db.execute(
                "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (self.KEY, dumps(settings.model_dump()), now_ist().isoformat()),
            )
            self._settings = settings
        for listener in self._listeners:
            listener(settings)
        return settings

    def reset(self) -> RuntimeSettings:
        with self._lock:
            self.db.execute("DELETE FROM settings WHERE key = ?", (self.KEY,))
            self._settings = RuntimeSettings()
        for listener in self._listeners:
            listener(self._settings)
        return self._settings
