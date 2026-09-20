"""Deterministic fakes for tests: environment, symbol registry, OHLCV, option chains, provider, adapter."""

from __future__ import annotations

import zlib
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from tradingagents.dataflows.india.fno import bs_price

from cc.agents.schema import AGENTS, AgentResult
from cc.analysis.options import years_to_expiry
from cc.config import EnvConfig, MarketHoursSettings
from cc.data.market_hours import market_status
from cc.data.models import (
    IST,
    DataUnavailable,
    InstrumentMeta,
    MarketStatus,
    OptionChain,
    OptionLeg,
    OptionRow,
    Quote,
    now_ist,
)
from cc.data.provider import (
    CAP_OHLCV_DAILY,
    CAP_OHLCV_INTRADAY,
    CAP_OPTION_CHAIN,
    CAP_QUOTES,
    MarketDataProvider,
)
from cc.data.symbols import SymbolRegistry

SECRET = "sk-test-secret-never-exposed-0123456789"
TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}


def make_env(**overrides) -> EnvConfig:
    base = EnvConfig(
        host="127.0.0.1", port=8765, db_path=Path(":memory:"), dev_mode=False, access_token="", qa_token="", ai_provider="openrouter",
        ai_base_url="http://ai.invalid/api/v1", ai_api_key_env="CC_TEST_AI_KEY", default_ai_model="test/default-550b",
        fallback_ai_model="test/fallback-120b", ai_timeout_seconds=5, ai_daily_call_budget=10, ai_model_cooldown_seconds=60,
        market_data_provider="public", option_data_provider="nse", execution_mode="analysis", live_execution_enabled=False,
        tradingview_widget_enabled=True, tradingview_library_path="", telegram_bot_token="", telegram_chat_id="",
        alert_webhook_url="", smtp_host="", smtp_port=587, smtp_user="", smtp_password="", alert_email_from="", alert_email_to="",
    )
    return replace(base, **overrides)


def intraday_index(n: int, minutes: int, start: str = "2026-08-03") -> pd.DatetimeIndex:
    stamps: list[pd.Timestamp] = []
    day = pd.Timestamp(start)
    while len(stamps) < n:
        if day.weekday() < 5:
            t = day + pd.Timedelta(hours=9, minutes=15)
            end = day + pd.Timedelta(hours=15, minutes=30)
            while t < end and len(stamps) < n:
                stamps.append(t)
                t += pd.Timedelta(minutes=minutes)
        day += pd.Timedelta(days=1)
    return pd.DatetimeIndex(stamps).tz_localize(IST)


def make_ohlcv(n: int = 400, freq: str = "5m", drift: float = 0.0, vol: float = 0.001, seed: int = 1, base: float = 23000.0,
               volume: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if freq == "1D":
        index = pd.bdate_range(end="2026-09-11", periods=n).tz_localize(IST)
    else:
        index = intraday_index(n, TF_MINUTES[freq])
    rets = drift + vol * rng.standard_normal(n)
    close = base * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[base], close[:-1]])
    wiggle = np.abs(rng.standard_normal(n)) * max(vol, 1e-4) / 2
    frame = pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * (1 + wiggle),
            "low": np.minimum(open_, close) * (1 - wiggle),
            "close": close,
            "volume": rng.integers(1000, 5000, n).astype(float) if volume else np.nan,
        },
        index=index,
    )
    frame.attrs = {"provider": "Fake test provider", "has_volume": volume, "fetched_at": "2026-09-11T15:30:00+05:30"}
    return frame


def make_chain(spot: float = 23400.0, expiry: date | None = None, iv: float = 0.12, step: float = 50, n: int = 20,
               with_iv: bool = True, lot: int | None = 65, symbol: str = "NIFTY") -> OptionChain:
    now = now_ist()
    expiry = expiry or (now + timedelta(days=4)).date()
    years = max(years_to_expiry(expiry, now), 1 / 365)
    atm = round(spot / step) * step
    rows = []
    for k in range(-n, n + 1):
        strike = atm + k * step
        ce_oi = 900_000.0 if k == 6 else 50_000.0 + 100 * k * k
        pe_oi = 1_000_000.0 if k == -4 else 60_000.0 + 100 * k * k

        def leg(price: float, oi: float) -> OptionLeg:
            price = round(price, 2)
            return OptionLeg(
                ltp=price if price >= 0.05 else None, change=1.0, change_pct=1.0, volume=10_000.0, oi=oi, oi_change=round(oi * 0.1),
                oi_change_pct=10.0, iv=iv * 100 if with_iv else None, bid=round(price * 0.99, 2) if price >= 0.05 else None,
                ask=round(price * 1.01, 2) if price >= 0.05 else None, bid_qty=50.0, ask_qty=50.0,
            )

        rows.append(OptionRow(float(strike), leg(bs_price(spot, strike, years, 0.065, iv, "CE"), ce_oi),
                              leg(bs_price(spot, strike, years, 0.065, iv, "PE"), pe_oi)))
    return OptionChain(symbol, expiry, spot, now, "Fake chain", rows, lot)


class FakeRegistry(SymbolRegistry):
    EQUITIES = {"RELIANCE": "Reliance Industries Ltd", "INFY": "Infosys Ltd", "TCS": "Tata Consultancy Services Ltd",
                "HDFCBANK": "HDFC Bank Ltd"}
    LOTS = {"NIFTY": 65, "BANKNIFTY": 30, "FINNIFTY": 60, "MIDCPNIFTY": 120, "RELIANCE": 500, "INFY": 400, "HDFCBANK": 550}

    def equities(self) -> dict[str, str]:
        return dict(self.EQUITIES)

    def lot_sizes(self) -> dict[str, int]:
        return dict(self.LOTS)

    def constituents(self, index_name: str = "NIFTY 50") -> list[dict]:
        return [{"symbol": s, "name": n, "industry": "Test industry"} for s, n in self.EQUITIES.items()]


def closed_market() -> MarketStatus:
    return market_status(datetime(2026, 9, 13, 11, 0, tzinfo=IST), MarketHoursSettings(), set())


def open_market() -> MarketStatus:
    return market_status(datetime(2026, 9, 11, 11, 0, tzinfo=IST), MarketHoursSettings(), set())


class FakeProvider(MarketDataProvider):
    name = "fake"
    label = "Fake test provider"
    capabilities = frozenset({CAP_QUOTES, CAP_OHLCV_INTRADAY, CAP_OHLCV_DAILY, CAP_OPTION_CHAIN})

    def __init__(self, registry: SymbolRegistry, market: MarketStatus | None = None):
        super().__init__()
        self.registry = registry
        self.market = market or closed_market()
        self.frames: dict[tuple[str, str], pd.DataFrame] = {}

    def get_ohlcv(self, symbol: str, timeframe: str, bars: int = 500) -> pd.DataFrame:
        key = (symbol, "1D" if timeframe in ("1D", "1W") else timeframe)
        if key not in self.frames:
            seed = zlib.crc32(f"{key[0]}:{key[1]}".encode()) % 10_000
            index = self.registry.is_index(symbol)
            self.frames[key] = make_ohlcv(900, "1D" if key[1] == "1D" else key[1] if key[1] in TF_MINUTES else "5m",
                                          drift=0.0002, vol=0.0015 if key[1] != "1D" else 0.01, seed=seed,
                                          base=23000.0 if index else 1500.0, volume=not index)
        frame = self.frames[key]
        out = self.frames[key].tail(bars).copy()
        out.attrs = dict(frame.attrs)
        return self._track(lambda: out)

    def get_quote(self, symbol: str) -> Quote:
        frame = self.get_ohlcv(symbol, "5m", 200)
        last = frame.iloc[-1]
        return Quote(symbol=symbol, price=float(last["close"]), prev_close=float(frame["close"].iloc[-76]), open=float(last["open"]),
                     high=float(last["high"]), low=float(last["low"]), volume=None, timestamp=frame.index[-1].to_pydatetime(),
                     provider=self.label)

    def get_expiries(self, symbol: str) -> list[date]:
        if self.registry.meta(symbol).option_type is None:
            raise DataUnavailable(f"{symbol} expiries", "instrument has no NSE-listed options", self.label)
        today = now_ist().date()
        return [today + timedelta(days=3), today + timedelta(days=24)]

    def get_option_chain(self, symbol: str, expiry: date) -> OptionChain:
        spot = self.get_quote(symbol).price
        step = 50 if self.registry.is_index(symbol) else 10
        return make_chain(spot=spot, expiry=expiry, step=step, n=60, lot=self.registry.meta(symbol).lot_size, symbol=symbol)

    def get_instrument_metadata(self, symbol: str) -> InstrumentMeta:
        return self.registry.meta(symbol)

    def get_market_status(self) -> MarketStatus:
        return self.market


class FakeAdapter:
    def run_analyst(self, agent: str, symbol: str, timeframe: str, context: str) -> AgentResult:
        return AgentResult(agent=agent, name=AGENTS[agent]["name"], timestamp=now_ist().isoformat(), symbol=symbol, timeframe=timeframe,
                           signal="BULLISH", confidence=70, confidence_basis="llm_assessed", reasoning="fake analyst view",
                           model="fake-model", report="Fake report mentioning support 23000.")

    def run_full_pipeline(self, symbol: str, analysts: list[str]) -> dict:
        raise NotImplementedError


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload
