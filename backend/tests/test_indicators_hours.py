from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest
from helpers import make_ohlcv
from pydantic import ValidationError

from cc.analysis.indicators import compute_indicators, has_real_volume, rsi, session_vwap
from cc.config import MarketHoursSettings, SignalSettings
from cc.data.market_hours import market_status
from cc.data.models import IST

H = MarketHoursSettings()


def at(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def test_rsi_bounds_and_trend():
    frame = make_ohlcv(300, drift=0.001, vol=0.0005)
    values = rsi(frame["close"], 14).dropna()
    assert ((values >= 0) & (values <= 100)).all()
    assert values.iloc[-1] > 60


def test_indicators_are_causal():
    frame = make_ohlcv(400, seed=3)
    cfg = SignalSettings()
    columns = ["ema_fast", "ema_slow", "rsi", "macd_hist", "atr", "supertrend", "adx", "vwap", "bb_width", "sma200"]
    full = compute_indicators(frame, cfg)[columns].iloc[:250]
    prefix = compute_indicators(frame.iloc[:250], cfg)[columns]
    pd.testing.assert_frame_equal(full, prefix, check_exact=False, rtol=1e-9)


def test_vwap_needs_real_volume():
    frame = make_ohlcv(200, volume=False)
    assert not has_real_volume(frame)
    assert session_vwap(frame).isna().all()
    out = compute_indicators(frame, SignalSettings())
    assert out["vwap"].isna().all() and out.attrs["has_volume"] is False


def test_vwap_resets_each_session():
    frame = make_ohlcv(200, volume=True)
    vwap = session_vwap(frame)
    first = frame.groupby(frame.index.date).head(1).index
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3
    assert np.allclose(vwap.loc[first], typical.loc[first])


def test_market_sessions():
    assert market_status(at(2026, 9, 11, 9, 5), H, set()).session == "PRE_OPEN"
    status = market_status(at(2026, 9, 11, 10, 0), H, set())
    assert status.session == "OPEN" and status.is_trading and status.next_open is None
    assert market_status(at(2026, 9, 11, 15, 10), H, set()).session == "CLOSING"
    assert market_status(at(2026, 9, 11, 15, 45), H, set()).session == "POST_CLOSE"
    assert market_status(at(2026, 9, 11, 20, 0), H, set()).session == "CLOSED"


def test_weekend_and_exchange_holiday():
    holidays = {date(2026, 9, 14)}
    weekend = market_status(at(2026, 9, 13, 11, 0), H, holidays)
    assert weekend.session == "CLOSED" and weekend.reason == "weekend"
    assert weekend.next_open == at(2026, 9, 15, 9, 15)
    assert weekend.session_date == date(2026, 9, 11)
    holiday = market_status(at(2026, 9, 14, 11, 0), H, holidays)
    assert holiday.reason == "exchange holiday" and not holiday.is_trading


def test_configured_holidays_and_validation():
    hours = MarketHoursSettings(extra_holidays=["2026-09-15"])
    assert market_status(at(2026, 9, 15, 10, 0), hours, set()).reason == "exchange holiday"
    with pytest.raises(ValidationError):
        MarketHoursSettings(market_open="15:45")
    with pytest.raises(ValidationError):
        MarketHoursSettings(extra_holidays=["15-09-2026"])
