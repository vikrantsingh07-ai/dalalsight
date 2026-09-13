"""MarketDataProvider abstraction.

Every provider implements the same methods and raises ``DataUnavailable`` instead of
returning placeholder values, so switching providers (public → broker feed) never changes
analysis code and never produces fake numbers.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import date, datetime
from typing import TypeVar

import pandas as pd

from .models import DataUnavailable, InstrumentMeta, MarketStatus, OptionChain, ProviderHealth, Quote, now_ist

T = TypeVar("T")

CAP_QUOTES = "quotes"
CAP_OHLCV_INTRADAY = "ohlcv_intraday"
CAP_OHLCV_DAILY = "ohlcv_daily"
CAP_INDEX_VOLUME = "index_volume"
CAP_OPTION_CHAIN = "option_chain"
CAP_MARKET_STATUS = "market_status"
CAP_STREAMING = "streaming"

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


class MarketDataProvider(ABC):
    """Interface for market data. OHLCV frames use a tz-aware (Asia/Kolkata) DatetimeIndex,
    lowercase columns ``open high low close volume`` (volume is NaN when the source has none),
    and ``frame.attrs`` carrying ``provider``, ``has_volume`` and ``fetched_at``."""

    name: str = "provider"
    label: str = "provider"
    capabilities: frozenset[str] = frozenset()

    def __init__(self) -> None:
        self._health_lock = threading.Lock()
        self._last_success: datetime | None = None
        self._last_error: str | None = None
        self._last_error_at: datetime | None = None
        self._latency_ms: float | None = None

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote: ...

    @abstractmethod
    def get_ohlcv(self, symbol: str, timeframe: str, bars: int = 500) -> pd.DataFrame: ...

    @abstractmethod
    def get_option_chain(self, symbol: str, expiry: date) -> OptionChain: ...

    @abstractmethod
    def get_expiries(self, symbol: str) -> list[date]: ...

    @abstractmethod
    def get_instrument_metadata(self, symbol: str) -> InstrumentMeta: ...

    @abstractmethod
    def get_market_status(self) -> MarketStatus: ...

    def get_quotes(self, symbols: list[str]) -> dict[str, Quote | DataUnavailable]:
        results: dict[str, Quote | DataUnavailable] = {}
        for symbol in symbols:
            try:
                results[symbol] = self.get_quote(symbol)
            except DataUnavailable as exc:
                results[symbol] = exc
        return results

    def get_ohlcv_batch(self, symbols: list[str], timeframe: str, bars: int = 500) -> dict[str, pd.DataFrame | DataUnavailable]:
        results: dict[str, pd.DataFrame | DataUnavailable] = {}
        for symbol in symbols:
            try:
                results[symbol] = self.get_ohlcv(symbol, timeframe, bars)
            except DataUnavailable as exc:
                results[symbol] = exc
        return results

    def health(self) -> ProviderHealth:
        with self._health_lock:
            if self._last_success is None and self._last_error is None:
                status, detail = "OFFLINE", "no requests yet"
            elif self._last_error_at and (self._last_success is None or self._last_error_at > self._last_success):
                status, detail = "DEGRADED", "last request failed"
            else:
                status, detail = "ONLINE", "last request succeeded"
            return ProviderHealth(
                name=self.label,
                status=status,
                detail=detail,
                last_success=self._last_success,
                last_error=self._last_error,
                last_error_at=self._last_error_at,
                latency_ms=self._latency_ms,
                capabilities=sorted(self.capabilities),
            )

    def _track(self, fn: Callable[[], T]) -> T:
        """Run a provider call and record success/failure and latency for System Health."""
        started = time.perf_counter()
        try:
            result = fn()
        except DataUnavailable as exc:
            self._record_error(str(exc))
            raise
        except Exception as exc:  # noqa: BLE001 — normalised into DataUnavailable below
            self._record_error(f"{type(exc).__name__}: {exc}")
            raise DataUnavailable(self.label, f"{type(exc).__name__}: {str(exc)[:200]}", self.label) from exc
        with self._health_lock:
            self._last_success = now_ist()
            self._latency_ms = round((time.perf_counter() - started) * 1000, 1)
        return result

    def _record_error(self, message: str) -> None:
        with self._health_lock:
            self._last_error = message[:300]
            self._last_error_at = now_ist()
