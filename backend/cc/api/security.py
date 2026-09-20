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


# Endpoints the low-privilege QA token may call (config.EnvConfig.qa_token) — for the scheduled QA/paper-trading
# routine (docs/DEPLOYMENT.md), which must never hold the full CC_ACCESS_TOKEN. Read-only information, plus the
# handful of writes needed to actually use the app: paper trading, scanner/strategy/hedge analysis, and closing
# out recorded signals. Deliberately excludes anything that spends the AI call budget (agents, assistant),
# changes persistent config (settings, alerts), or could surprise the human user (a test alert send, replay mode,
# a new backtest job). Paths are matched without the "/api" prefix.
QA_TOKEN_GET_EXACT = frozenset({
    "/status", "/config", "/symbols/search", "/quotes", "/overview", "/strategies/suggest", "/commentary",
    "/agents/meta", "/agents/runs", "/alerts", "/alerts/events", "/signals", "/signals/stats",
    "/paper/orders", "/paper/positions", "/backtest", "/timeline", "/errors", "/health", "/replay/status",
    "/tradingview/pine",
})
QA_TOKEN_GET_PREFIX = (
    "/instrument/", "/chart/", "/analysis/", "/options/", "/stocks/", "/agents/runs/", "/signals/history/",
    "/backtest/", "/calibration/",
)
QA_TOKEN_POST_EXACT = frozenset({"/signals/evaluate", "/paper/orders", "/scanner/run", "/strategies/build", "/hedging/analyze"})


def qa_scope_allows(method: str, path: str) -> bool:
    route = path.removeprefix("/api")
    if method == "GET":
        return route in QA_TOKEN_GET_EXACT or route.startswith(QA_TOKEN_GET_PREFIX)
    if method == "POST":
        return route in QA_TOKEN_POST_EXACT
    return False


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
