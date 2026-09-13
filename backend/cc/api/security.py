"""Request security helpers: optional access token, rate limiting, JSON-safe responses."""

from __future__ import annotations

import hmac
import json
import math
import threading
import time
from collections import deque
from dataclasses import is_dataclass
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, client: str, bucket: str, limit: int, window_seconds: float) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault((client, bucket), deque())
            while hits and now - hits[0] > window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                retry = int(window_seconds - (now - hits[0])) + 1
                raise HTTPException(429, detail=f"rate limit for {bucket}: {limit} requests per {int(window_seconds)}s; retry in {retry}s")
            hits.append(now)


def token_ok(expected: str, provided: str | None) -> bool:
    if not expected:
        return True
    if not provided:
        return False
    return hmac.compare_digest(expected.encode(), provided.encode())


def sanitize(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return sanitize(value.model_dump())
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):  # numpy scalar
        return sanitize(value.item())
    if is_dataclass(value) and hasattr(value, "to_dict"):
        return sanitize(value.to_dict())
    return value


class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(sanitize(content), ensure_ascii=False, allow_nan=False, separators=(",", ":"), default=str).encode("utf-8")


def respond(content: Any, status_code: int = 200) -> SafeJSONResponse:
    return SafeJSONResponse(content, status_code=status_code)
