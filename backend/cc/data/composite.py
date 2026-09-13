"""Composite public provider: routes each request to the best free source and records provenance.

* index quotes → NSE (fallback Yahoo); stock quotes → Yahoo
* OHLCV → Yahoo; stale or sparse index feeds fall back to NSE (daily history, current-session
  ticks); during the session the latest index bars are refreshed from NSE 1-second ticks
* option chains / expiries → NSE
* market status → configured calendar + NSE holiday list + NSE status message
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from datetime import date, timedelta

import pandas as pd

from ..config import TIMEFRAME_MINUTES, MarketHoursSettings
from .market_hours import market_status
from .models import DataUnavailable, InstrumentMeta, MarketStatus, OptionChain, ProviderHealth, Quote, now_ist
from .nse import TICK_RULES, NSEPublicProvider
from .provider import MarketDataProvider
from .symbols import SymbolRegistry
from .yahoo import YahooProvider


class CompositePublicProvider(MarketDataProvider):
    name = "public"
    label = "Public composite (NSE public API + Yahoo Finance)"

    def __init__(self, yahoo: YahooProvider, nse: NSEPublicProvider, registry: SymbolRegistry,
                 hours: Callable[[], MarketHoursSettings]):
        super().__init__()
        self.yahoo = yahoo
        self.nse = nse
        self.registry = registry
        self._hours = hours
        self.capabilities = yahoo.capabilities | nse.capabilities

    # ------------------------------------------------------------------ quotes
    def get_quote(self, symbol: str) -> Quote:
        info = self.registry.index_info(symbol)
        if info and info.nse_name:
            try:
                return self.nse.get_quote(symbol)
            except DataUnavailable:
                pass
        return self.yahoo.get_quote(symbol)

    def get_quotes(self, symbols: list[str]) -> dict[str, Quote | DataUnavailable]:
        results: dict[str, Quote | DataUnavailable] = {}
        stocks = []
        for symbol in symbols:
            info = self.registry.index_info(symbol)
            if info and info.nse_name:
                try:
                    results[symbol] = self.nse.get_quote(symbol)
                    continue
                except DataUnavailable:
                    pass
            stocks.append(symbol)
        if stocks:
            results.update(self.yahoo.get_quotes(stocks))
        return results

    # ------------------------------------------------------------------ OHLCV
    def get_ohlcv_batch(self, symbols: list[str], timeframe: str, bars: int = 500) -> dict[str, pd.DataFrame | DataUnavailable]:
        stocks = [s for s in symbols if self.registry.index_info(s) is None]
        results = self.yahoo.get_ohlcv_batch(stocks, timeframe, bars) if stocks else {}
        for symbol in symbols:
            if symbol not in results:
                try:
                    results[symbol] = self.get_ohlcv(symbol, timeframe, bars)
                except DataUnavailable as exc:
                    results[symbol] = exc
        return results

    def get_ohlcv(self, symbol: str, timeframe: str, bars: int = 500) -> pd.DataFrame:
        status = self.get_market_status()
        info = self.registry.index_info(symbol)
        if info is None:
            frame = self.yahoo.get_ohlcv(symbol, timeframe, bars)
            self._check_fresh(frame, symbol, timeframe, status, raise_if_stale=True)
            return frame

        yahoo_frame: pd.DataFrame | None = None
        yahoo_error: DataUnavailable | None = None
        try:
            yahoo_frame = self.yahoo.get_ohlcv(symbol, timeframe, bars)
        except DataUnavailable as exc:
            yahoo_error = exc

        usable = yahoo_frame is not None and len(yahoo_frame) >= min(60, bars) and not self._check_fresh(
            yahoo_frame, symbol, timeframe, status, raise_if_stale=False
        )
        if usable:
            if status.is_trading and timeframe in TICK_RULES and info.nse_name:
                yahoo_frame = self._merge_live_ticks(yahoo_frame, symbol, timeframe)
            return yahoo_frame

        if not info.nse_name:
            raise yahoo_error or DataUnavailable(f"{symbol} {timeframe}", "Yahoo feed stale or sparse and no NSE fallback for BSE indices", self.label)
        try:
            frame = self.nse.get_ohlcv(symbol, timeframe, bars)
        except DataUnavailable as exc:
            reason = "Yahoo feed stale/sparse" if yahoo_error is None else yahoo_error.reason
            raise DataUnavailable(
                f"{symbol} {timeframe} OHLCV", f"{reason}; NSE fallback: {exc.reason}", self.label,
                "a broker feed for multi-session intraday index history" if timeframe in TICK_RULES else "",
            ) from exc
        frame.attrs["provider"] = f"{self.nse.label} (Yahoo feed stale or sparse)"
        return frame

    def _check_fresh(self, frame: pd.DataFrame, symbol: str, timeframe: str, status: MarketStatus, raise_if_stale: bool) -> bool:
        """Return True when the frame is stale relative to the last session."""
        if frame.empty:
            if raise_if_stale:
                raise DataUnavailable(f"{symbol} {timeframe}", "provider returned no bars", frame.attrs.get("provider", ""))
            return True
        last = frame.index[-1]
        stale_by_days = (status.session_date - last.date()).days
        stale = stale_by_days > (7 if timeframe == "1W" else 3)
        if status.is_trading and TIMEFRAME_MINUTES[timeframe] < 1440:
            lag = now_ist() - last.to_pydatetime()
            frame.attrs["lag_seconds"] = round(lag.total_seconds())
            stale = stale or lag > timedelta(minutes=max(30, 3 * TIMEFRAME_MINUTES[timeframe]))
        frame.attrs["stale"] = stale
        if stale and raise_if_stale:
            raise DataUnavailable(f"{symbol} {timeframe}", f"latest bar {last} is stale", frame.attrs.get("provider", ""))
        return stale

    def _merge_live_ticks(self, frame: pd.DataFrame, symbol: str, timeframe: str) -> pd.DataFrame:
        try:
            live = self.nse.get_ohlcv(symbol, timeframe, 500)
        except DataUnavailable:
            return frame
        if live.empty:
            return frame
        session_start = live.index[0].normalize()
        merged = pd.concat([frame[frame.index < session_start], live])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        merged.attrs = dict(frame.attrs)
        merged.attrs["provider"] = f"{frame.attrs.get('provider')}; current session from {self.nse.label} ticks"
        merged.attrs["live_ticks_merged"] = True
        return merged

    # ------------------------------------------------------------------ options / meta / status
    def get_option_chain(self, symbol: str, expiry: date) -> OptionChain:
        return self.nse.get_option_chain(symbol, expiry)

    def get_expiries(self, symbol: str) -> list[date]:
        return self.nse.get_expiries(symbol)

    def get_instrument_metadata(self, symbol: str) -> InstrumentMeta:
        return self.registry.meta(symbol)

    def get_market_status(self) -> MarketStatus:
        hours = self._hours()
        try:
            holidays = self.nse.holidays()
        except DataUnavailable:
            holidays = set()
        message = None
        with contextlib.suppress(DataUnavailable):
            message = self.nse.exchange_status().get("message")
        status = market_status(now_ist(), hours, holidays, message)
        if not holidays:
            status.reason += " (NSE holiday list unavailable; weekends and configured holidays only)"
        return status

    def health(self) -> ProviderHealth:
        children = [self.nse.health(), self.yahoo.health()]
        # A feed that has not been asked for anything yet is idle, not offline.
        used = [c for c in children if c.last_success is not None or c.last_error is not None]
        if not used:
            return ProviderHealth(name=self.label, status="OFFLINE", detail="no requests yet", capabilities=sorted(self.capabilities))
        order = {"ONLINE": 0, "DEGRADED": 1, "OFFLINE": 2, "ERROR": 3}
        worst = max(used, key=lambda c: order.get(c.status, 0)).status
        detail = "; ".join(f"{c.name}: {c.status if c in used else 'idle'}" for c in children)
        return ProviderHealth(name=self.label, status=worst, detail=detail, capabilities=sorted(self.capabilities))

    def child_health(self) -> list[ProviderHealth]:
        return [self.nse.health(), self.yahoo.health()]
