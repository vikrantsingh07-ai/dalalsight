"""In-process event bus: services publish from any thread, WebSocket clients consume."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from typing import Any

from ..data.models import now_ist


class EventBus:
    def __init__(self, queue_size: int = 500):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self._queue_size = queue_size

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def client_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def publish(self, event_type: str, data: Any) -> None:
        message = {"type": event_type, "ts": now_ist().isoformat(), "data": data}
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._fanout(message)
        else:
            loop.call_soon_threadsafe(self._fanout, message)

    def _fanout(self, message: dict) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()  # drop the oldest message for slow clients
            queue.put_nowait(message)
