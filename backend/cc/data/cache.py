"""Small thread-safe TTL cache used to avoid repeated provider calls."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Hashable
from typing import Any, TypeVar

T = TypeVar("T")


class TTLCache:
    def __init__(self, max_items: int = 2048):
        self._items: dict[Hashable, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._key_locks: dict[Hashable, threading.Lock] = {}
        self._max_items = max_items

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            item = self._items.get(key)
            if item and item[0] > time.monotonic():
                return item[1]
            return None

    def set(self, key: Hashable, value: Any, ttl: float) -> None:
        with self._lock:
            if len(self._items) >= self._max_items:
                now = time.monotonic()
                expired = [k for k, (exp, _) in self._items.items() if exp <= now]
                for k in expired or list(self._items)[: self._max_items // 10]:
                    self._items.pop(k, None)
            self._items[key] = (time.monotonic() + ttl, value)

    def get_or_set(self, key: Hashable, ttl: float, factory: Callable[[], T]) -> T:
        cached = self.get(key)
        if cached is not None:
            return cached
        with self._lock:
            key_lock = self._key_locks.setdefault(key, threading.Lock())
        with key_lock:  # one fetch per key at a time
            cached = self.get(key)
            if cached is not None:
                return cached
            value = factory()
            self.set(key, value, ttl)
            return value

    def invalidate(self, prefix: Hashable | None = None) -> None:
        with self._lock:
            if prefix is None:
                self._items.clear()
                return
            for key in [k for k in self._items if isinstance(k, tuple) and k and k[0] == prefix]:
                self._items.pop(key, None)
