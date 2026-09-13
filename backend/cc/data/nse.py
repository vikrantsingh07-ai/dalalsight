"""NSE public website API provider: index quotes and breadth, session status, holidays,
live option chains and current-session index ticks.

These endpoints are unofficial (no SLA, may throttle or change). Every failure surfaces as
``DataUnavailable`` and in System Health.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from tradingagents.dataflows.india.index_history import fetch_nse_index_history
from tradingagents.dataflows.india.nse_client import nse_api_json

from .cache import TTLCache
from .models import (
    IST,
    DataUnavailable,
    InstrumentMeta,
    MarketStatus,
    OptionChain,
    OptionLeg,
    OptionRow,
    Quote,
)
from .provider import (
    CAP_MARKET_STATUS,
    CAP_OHLCV_DAILY,
    CAP_OHLCV_INTRADAY,
    CAP_OPTION_CHAIN,
    CAP_QUOTES,
    MarketDataProvider,
)
from .symbols import SymbolRegistry
from .yahoo import resample_ohlcv


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(number) else number


def _positive(value) -> float | None:
    number = _num(value)
    return number if number and number > 0 else None


def _nse_datetime(value: str) -> datetime:
    for pattern in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            return datetime.strptime(str(value).strip(), pattern).replace(tzinfo=IST)
        except ValueError:
            continue
    raise ValueError(f"unrecognised NSE timestamp {value!r}")


TICK_RULES = {"1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "60min"}


class NSEPublicProvider(MarketDataProvider):
    name = "nse"
    label = "NSE public website API (unofficial)"
    capabilities = frozenset({CAP_QUOTES, CAP_OPTION_CHAIN, CAP_MARKET_STATUS, CAP_OHLCV_INTRADAY, CAP_OHLCV_DAILY})

    def __init__(self, registry: SymbolRegistry, cache: TTLCache):
        super().__init__()
        self.registry = registry
        self.cache = cache

    def _json(self, path: str, params: dict | None = None):
        # Failures are remembered briefly so an unreachable NSE site does not stall every request.
        fail_key = ("nse_fail", path, tuple(sorted((params or {}).items())))
        failure = self.cache.get(fail_key)
        if failure is not None:
            raise failure
        try:
            return self._track(lambda: nse_api_json(path, params, timeout=12.0, attempts=2))
        except DataUnavailable as exc:
            self.cache.set(fail_key, exc, 45)
            raise

    # ------------------------------------------------------------------ indices
    def all_indices(self) -> dict:
        def load() -> dict:
            payload = self._json("allIndices")
            rows = {row.get("index"): row for row in payload.get("data", []) if isinstance(row, dict)}
            return {"rows": rows, "timestamp": _nse_datetime(payload["timestamp"]), "breadth": {
                "advances": _num(payload.get("advances")), "declines": _num(payload.get("declines")),
                "unchanged": _num(payload.get("unchanged")),
            }}

        return self.cache.get_or_set(("nse_all_indices",), 10, load)

    def get_quote(self, symbol: str) -> Quote:
        info = self.registry.index_info(symbol)
        if not info or not info.nse_name:
            raise DataUnavailable(f"{symbol} quote", "NSE public API quotes cover NSE indices only (equity quotes are blocked)", self.label)
        data = self.all_indices()
        row = data["rows"].get(info.nse_name)
        if not row:
            raise DataUnavailable(f"{symbol} quote", f"{info.nse_name} missing from NSE allIndices", self.label)
        return Quote(
            symbol=symbol,
            price=float(row["last"]),
            prev_close=_num(row.get("previousClose")),
            open=_num(row.get("open")),
            high=_num(row.get("high")),
            low=_num(row.get("low")),
            volume=None,
            timestamp=data["timestamp"],
            provider=self.label,
            change=_num(row.get("variation")),
            change_pct=_num(row.get("percentChange")),
            extra={
                "advances": _num(row.get("advances")),
                "declines": _num(row.get("declines")),
                "unchanged": _num(row.get("unchanged")),
                "year_high": _num(row.get("yearHigh")),
                "year_low": _num(row.get("yearLow")),
                "pe": _num(row.get("pe")),
                "pb": _num(row.get("pb")),
            },
        )

    def index_ticks(self, symbol: str) -> pd.Series:
        info = self.registry.index_info(symbol)
        if not info or not info.nse_name:
            raise DataUnavailable(f"{symbol} intraday ticks", "not an NSE index", self.label)

        def load() -> pd.Series:
            payload = self._json("chart-databyindex-dynamic", {"index": info.nse_name, "type": "index"})
            points = payload.get("grapthData") or []
            normal = [p for p in points if len(p) >= 2 and (len(p) < 3 or p[2] == "NM")]
            if not normal:
                raise DataUnavailable(f"{symbol} intraday ticks", "no normal-market ticks yet", self.label)
            # NSE encodes IST wall-clock time as epoch milliseconds and keeps tagging the
            # 15:30–15:40 closing-session prints "NM"; bars use the 09:15–15:30 normal market only.
            index = pd.to_datetime([int(p[0]) for p in normal], unit="ms").tz_localize(IST)
            series = pd.Series([float(p[1]) for p in normal], index=index).sort_index()
            minutes = series.index.hour * 60 + series.index.minute
            series = series[(minutes >= 9 * 60 + 15) & (minutes < 15 * 60 + 30)]
            if series.empty:
                raise DataUnavailable(f"{symbol} intraday ticks", "no normal-market ticks yet", self.label)
            return series

        return self.cache.get_or_set(("nse_ticks", symbol), 15, load)

    def get_ohlcv(self, symbol: str, timeframe: str, bars: int = 500) -> pd.DataFrame:
        info = self.registry.index_info(symbol)
        if not info or not info.nse_name:
            raise DataUnavailable(f"{symbol} OHLCV", "NSE public API history covers NSE indices only", self.label)
        if timeframe in TICK_RULES:
            ticks = self.index_ticks(symbol)
            frame = ticks.resample(TICK_RULES[timeframe], origin="start_day", label="left", closed="left").ohlc()
            frame["volume"] = np.nan
            frame = frame.dropna(subset=["close"])
        elif timeframe in ("1D", "1W"):
            end = date.today()
            start = end - timedelta(days=730)
            history = self.cache.get_or_set(
                ("nse_index_history", info.nse_name, start), 3600,
                lambda: self._track(lambda: fetch_nse_index_history(info.nse_name, start, end)),
            )
            if history.empty:
                raise DataUnavailable(f"{symbol} daily history", "NSE returned no rows", self.label)
            frame = history.rename(columns=str.lower)
            frame.index = pd.DatetimeIndex(frame.index).tz_localize(IST)
            frame["volume"] = np.nan  # traded quantity of constituents is not index volume
            if timeframe == "1W":
                frame = resample_ohlcv(frame, "W-MON")
        else:
            raise DataUnavailable(f"{symbol} {timeframe} OHLCV", "NSE public API has no multi-session intraday history", self.label)
        frame = frame[["open", "high", "low", "close", "volume"]].tail(bars)
        frame.attrs = {"provider": self.label, "symbol": symbol, "timeframe": timeframe, "has_volume": False}
        return frame

    # ------------------------------------------------------------------ status / calendar
    def exchange_status(self) -> dict:
        def load() -> dict:
            payload = self._json("marketStatus")
            for row in payload.get("marketState", []):
                if row.get("market") == "Capital Market":
                    return {"status": row.get("marketStatus"), "message": row.get("marketStatusMessage"), "trade_date": row.get("tradeDate")}
            return {}

        return self.cache.get_or_set(("nse_market_status",), 30, load)

    def holidays(self) -> set[date]:
        def load() -> set[date]:
            payload = self._json("holiday-master", {"type": "trading"})
            days = set()
            for row in payload.get("CM", []):
                try:
                    days.add(datetime.strptime(row["tradingDate"], "%d-%b-%Y").date())
                except (KeyError, ValueError):
                    continue
            return days

        return self.cache.get_or_set(("nse_holidays",), 12 * 3600, load)

    def get_market_status(self) -> MarketStatus:
        raise DataUnavailable("market status", "use the composite provider, which combines NSE status with the configured calendar", self.label)

    # ------------------------------------------------------------------ options
    def _option_symbol(self, symbol: str) -> tuple[str, str]:
        meta = self.registry.meta(symbol)
        if meta.option_type is None:
            raise DataUnavailable(f"{symbol} options", "instrument has no NSE-listed options", self.label)
        return meta.option_type, symbol

    def get_expiries(self, symbol: str) -> list[date]:
        self._option_symbol(symbol)

        def load() -> list[date]:
            payload = self._json("option-chain-contract-info", {"symbol": symbol})
            expiries = []
            for value in payload.get("expiryDates", []):
                try:
                    expiries.append(datetime.strptime(value, "%d-%b-%Y").date())
                except ValueError:
                    continue
            if not expiries:
                raise DataUnavailable(f"{symbol} expiries", "NSE returned no expiries", self.label)
            return sorted(expiries)

        return self.cache.get_or_set(("nse_expiries", symbol), 1800, load)

    def get_option_chain(self, symbol: str, expiry: date) -> OptionChain:
        option_type, nse_symbol = self._option_symbol(symbol)

        def load() -> OptionChain:
            payload = self._json(
                "option-chain-v3", {"type": option_type, "symbol": nse_symbol, "expiry": expiry.strftime("%d-%b-%Y")}
            )
            records = payload.get("records") or {}
            data = records.get("data") or []
            if not data:
                raise DataUnavailable(f"{symbol} {expiry} option chain", "NSE returned an empty chain", self.label)
            rows = [OptionRow(strike=float(item["strikePrice"]), ce=_leg(item.get("CE")), pe=_leg(item.get("PE"))) for item in data]
            rows.sort(key=lambda r: r.strike)
            spot = _num(records.get("underlyingValue")) or next(
                (_num(item[side].get("underlyingValue")) for item in data for side in ("CE", "PE") if item.get(side)), None
            )
            if not spot:
                raise DataUnavailable(f"{symbol} option chain", "no underlying value in NSE response", self.label)
            stamp = records.get("timestamp")
            if not stamp:
                raise DataUnavailable(f"{symbol} option chain", "NSE response has no timestamp", self.label)
            return OptionChain(
                symbol=symbol, expiry=expiry, spot=spot, timestamp=_nse_datetime(stamp),
                provider=self.label, rows=rows, lot_size=self.registry.meta(symbol).lot_size,
            )

        return self.cache.get_or_set(("nse_chain", symbol, expiry), 45, load)

    def get_instrument_metadata(self, symbol: str) -> InstrumentMeta:
        return self.registry.meta(symbol)


def _leg(raw: dict | None) -> OptionLeg | None:
    if not raw:
        return None
    return OptionLeg(
        ltp=_positive(raw.get("lastPrice")),
        change=_num(raw.get("change")),
        change_pct=_num(raw.get("pChange")),
        volume=_num(raw.get("totalTradedVolume")),
        oi=_num(raw.get("openInterest")),
        oi_change=_num(raw.get("changeinOpenInterest")),
        oi_change_pct=_num(raw.get("pchangeinOpenInterest")),
        iv=_positive(raw.get("impliedVolatility")),
        bid=_positive(raw.get("buyPrice1")),
        ask=_positive(raw.get("sellPrice1")),
        bid_qty=_num(raw.get("buyQuantity1")),
        ask_qty=_num(raw.get("sellQuantity1")),
    )
