"""Yahoo Finance provider (yfinance): stock and index OHLCV, stock quotes.

Yahoo carries no NSE option chains and no volume for spot indices; both limitations are
reported through ``DataUnavailable`` / ``attrs['has_volume']`` rather than papered over.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf

from ..config import TIMEFRAME_MINUTES
from .cache import TTLCache
from .models import IST, DataUnavailable, InstrumentMeta, MarketStatus, OptionChain, Quote, now_ist
from .provider import CAP_OHLCV_DAILY, CAP_OHLCV_INTRADAY, CAP_QUOTES, OHLCV_COLUMNS, MarketDataProvider
from .symbols import SymbolRegistry

# timeframe -> (yahoo interval, period, resample rule)
YAHOO_TIMEFRAMES: dict[str, tuple[str, str, str | None]] = {
    "1m": ("1m", "7d", None),
    "3m": ("1m", "7d", "3min"),
    "5m": ("5m", "60d", None),
    "15m": ("15m", "60d", None),
    "30m": ("30m", "60d", None),
    "1h": ("60m", "730d", None),
    "4h": ("60m", "730d", "4h"),
    "1D": ("1d", "5y", None),
    "1W": ("1wk", "10y", None),
}


def normalise_frame(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.rename(columns=str.lower)
    missing = [c for c in ("open", "high", "low", "close") if c not in frame.columns]
    if missing:
        raise DataUnavailable("OHLCV", f"missing columns {missing}")
    if "volume" not in frame.columns:
        frame["volume"] = np.nan
    frame = frame[OHLCV_COLUMNS].apply(pd.to_numeric, errors="coerce")
    index = pd.DatetimeIndex(frame.index)
    frame.index = index.tz_localize(IST) if index.tz is None else index.tz_convert(IST)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    frame = frame.dropna(subset=["close"])
    if len(frame) and (frame["volume"].fillna(0) == 0).all():
        frame["volume"] = np.nan  # Yahoo reports 0 for indices: that is "no data", not zero volume
    return frame


def resample_ohlcv(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample intraday bars; 4h bars are anchored to the 09:15 NSE open (09:15–13:15, 13:15–15:30)."""
    if rule.startswith("W"):
        grouped = frame.resample(rule, label="left", closed="left")
    else:
        offset = "75min" if rule == "4h" else None
        grouped = frame.resample(rule, origin="start_day", offset=offset, label="left", closed="left")
    out = pd.DataFrame(
        {
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
            "volume": grouped["volume"].sum(min_count=1),
        }
    )
    out = out.dropna(subset=["close"])
    out.attrs = dict(frame.attrs)
    return out


class YahooProvider(MarketDataProvider):
    name = "yahoo"
    label = "Yahoo Finance via yfinance (delay not guaranteed)"
    capabilities = frozenset({CAP_QUOTES, CAP_OHLCV_INTRADAY, CAP_OHLCV_DAILY})

    def __init__(self, registry: SymbolRegistry, cache: TTLCache):
        super().__init__()
        self.registry = registry
        self.cache = cache

    def yahoo_symbol(self, symbol: str) -> str:
        meta = self.registry.meta(symbol)
        if not meta.yahoo_symbol:
            raise DataUnavailable(symbol, "no Yahoo symbol mapping", self.label)
        return meta.yahoo_symbol

    def _download(self, ysym: str, interval: str, period: str) -> pd.DataFrame:
        raw = yf.Ticker(ysym).history(interval=interval, period=period, auto_adjust=False)
        if raw is None or raw.empty:
            raise DataUnavailable(ysym, f"Yahoo returned no {interval} bars", self.label)
        return normalise_frame(raw)

    def get_ohlcv(self, symbol: str, timeframe: str, bars: int = 500) -> pd.DataFrame:
        if timeframe not in YAHOO_TIMEFRAMES:
            raise ValueError(f"unsupported timeframe {timeframe}")
        interval, period, rule = YAHOO_TIMEFRAMES[timeframe]
        ysym = self.yahoo_symbol(symbol)
        ttl = 20 if TIMEFRAME_MINUTES[timeframe] < 1440 else 900
        frame = self.cache.get_or_set(
            ("yahoo_ohlcv", ysym, interval, period), ttl, lambda: self._track(lambda: self._download(ysym, interval, period))
        )
        if rule:
            frame = resample_ohlcv(frame, rule)
        frame = frame.tail(bars).copy()
        frame.attrs = {
            "provider": self.label,
            "symbol": symbol,
            "timeframe": timeframe,
            "has_volume": bool(frame["volume"].notna().mean() > 0.9) if len(frame) else False,
            "fetched_at": now_ist().isoformat(),
        }
        return frame

    def get_quote(self, symbol: str) -> Quote:
        intraday = self.get_ohlcv(symbol, "1m", bars=800)
        daily = self.get_ohlcv(symbol, "1D", bars=10)
        return quote_from_frames(symbol, intraday, daily, self.label)

    def get_quotes(self, symbols: list[str]) -> dict[str, Quote | DataUnavailable]:
        results: dict[str, Quote | DataUnavailable] = {}
        mapping: dict[str, str] = {}
        for symbol in symbols:
            try:
                mapping[symbol] = self.yahoo_symbol(symbol)
            except DataUnavailable as exc:
                results[symbol] = exc
        if not mapping:
            return results
        tickers = sorted(set(mapping.values()))
        key = ("yahoo_batch", tuple(tickers))
        try:
            intraday_raw, daily_raw = self.cache.get_or_set(
                key, 20, lambda: self._track(lambda: (
                    yf.download(tickers, period="2d", interval="1m", group_by="ticker", progress=False, threads=True, auto_adjust=False),
                    yf.download(tickers, period="10d", interval="1d", group_by="ticker", progress=False, threads=True, auto_adjust=False),
                ))
            )
        except DataUnavailable as exc:
            for symbol in mapping:
                results[symbol] = exc
            return results
        for symbol, ysym in mapping.items():
            try:
                intraday = normalise_frame(_ticker_slice(intraday_raw, ysym))
                daily = normalise_frame(_ticker_slice(daily_raw, ysym))
                results[symbol] = quote_from_frames(symbol, intraday, daily, self.label)
            except (DataUnavailable, KeyError, IndexError) as exc:
                results[symbol] = exc if isinstance(exc, DataUnavailable) else DataUnavailable(symbol, "no quote in batch", self.label)
        return results

    def get_ohlcv_batch(self, symbols: list[str], timeframe: str, bars: int = 500) -> dict[str, pd.DataFrame | DataUnavailable]:
        if timeframe != "1D" or len(symbols) < 2:
            return super().get_ohlcv_batch(symbols, timeframe, bars)
        results: dict[str, pd.DataFrame | DataUnavailable] = {}
        mapping: dict[str, str] = {}
        for symbol in symbols:
            try:
                mapping[symbol] = self.yahoo_symbol(symbol)
            except DataUnavailable as exc:
                results[symbol] = exc
        tickers = sorted(set(mapping.values()))
        if not tickers:
            return results
        try:
            raw = self.cache.get_or_set(("yahoo_daily_batch", tuple(tickers)), 900, lambda: self._track(
                lambda: yf.download(tickers, period="2y", interval="1d", group_by="ticker", progress=False, threads=True, auto_adjust=False)))
        except DataUnavailable as exc:
            return {**results, **{symbol: exc for symbol in mapping}}
        for symbol, ysym in mapping.items():
            try:
                frame = normalise_frame(_ticker_slice(raw, ysym)).tail(bars).copy()
            except (DataUnavailable, KeyError):
                results[symbol] = DataUnavailable(f"{symbol} daily bars", "not returned in the Yahoo batch download", self.label)
                continue
            if frame.empty:
                results[symbol] = DataUnavailable(f"{symbol} daily bars", "Yahoo returned no rows", self.label)
                continue
            frame.attrs = {"provider": self.label, "symbol": symbol, "timeframe": "1D",
                           "has_volume": bool(frame["volume"].notna().mean() > 0.9), "fetched_at": now_ist().isoformat()}
            results[symbol] = frame
        return results

    def get_option_chain(self, symbol: str, expiry: date) -> OptionChain:
        raise DataUnavailable(f"{symbol} option chain", "Yahoo Finance has no NSE option chains", self.label, "NSE option-chain provider")

    def get_expiries(self, symbol: str) -> list[date]:
        raise DataUnavailable(f"{symbol} expiries", "Yahoo Finance has no NSE option chains", self.label, "NSE option-chain provider")

    def get_instrument_metadata(self, symbol: str) -> InstrumentMeta:
        return self.registry.meta(symbol)

    def get_market_status(self) -> MarketStatus:
        raise DataUnavailable("market status", "Yahoo Finance does not publish NSE session status", self.label)


def _ticker_slice(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if isinstance(raw.columns, pd.MultiIndex):
        if ticker not in raw.columns.get_level_values(0):
            raise KeyError(ticker)
        return raw[ticker].dropna(how="all")
    return raw.dropna(how="all")


def quote_from_frames(symbol: str, intraday: pd.DataFrame, daily: pd.DataFrame, provider: str) -> Quote:
    if intraday.empty:
        raise DataUnavailable(symbol, "no intraday bars for a quote", provider)
    last = intraday.iloc[-1]
    last_day = intraday.index[-1].date()
    session = intraday[intraday.index.date == last_day]
    prior_daily = daily[daily.index.date < last_day] if len(daily) else daily
    prev_close = float(prior_daily["close"].iloc[-1]) if len(prior_daily) else None
    volume = session["volume"].sum(min_count=1)
    return Quote(
        symbol=symbol,
        price=float(last["close"]),
        prev_close=prev_close,
        open=float(session["open"].iloc[0]),
        high=float(session["high"].max()),
        low=float(session["low"].min()),
        volume=None if pd.isna(volume) else float(volume),
        timestamp=intraday.index[-1].to_pydatetime(),
        provider=provider,
        extra={"basis": "last 1-minute bar"},
    )
