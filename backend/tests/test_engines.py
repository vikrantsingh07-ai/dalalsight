import numpy as np
import pandas as pd
import pytest
from helpers import make_ohlcv

from cc.analysis.events import detect_events
from cc.analysis.indicators import compute_indicators
from cc.analysis.levels import compute_levels, swing_points
from cc.analysis.regime import detect_regime
from cc.analysis.signal_engine import LABEL_NO_TRADE, build_plan, build_signal
from cc.config import RuntimeSettings, SignalSettings, SignalWeights
from cc.data.models import IST


def analyse(frame, settings: RuntimeSettings | None = None, options=None):
    settings = settings or RuntimeSettings()
    ind = compute_indicators(frame, settings.signal)
    levels = compute_levels(ind, True, settings.signal.swing_lookback, settings.signal.breakout_lookback)
    events = detect_events(ind, levels, settings.signal)
    regime = detect_regime(ind)
    signal = build_signal("TEST", "5m", ind, events, levels, regime, options, settings.signal, settings.risk, ["fake"])
    return signal, ind, levels, regime


def test_uptrend_scores_bullish_and_downtrend_bearish():
    up, *_ = analyse(make_ohlcv(400, drift=0.0012, vol=0.0008, seed=5))
    down, *_ = analyse(make_ohlcv(400, drift=-0.0012, vol=0.0008, seed=6))
    assert up.composite > 0 and up.bullish_pct > 60
    assert down.composite < 0 and down.bearish_pct > 60
    assert next(c for c in up.components if c.name == "trend").score > 0


def test_signal_is_deterministic_and_probabilities_complement():
    frame = make_ohlcv(400, seed=7)
    a, *_ = analyse(frame)
    b, *_ = analyse(frame)
    assert a.to_dict() == b.to_dict()
    assert a.bullish_pct + a.bearish_pct == pytest.approx(100)


def test_unavailable_components_are_excluded_and_reported():
    signal, *_ = analyse(make_ohlcv(400, volume=False, seed=8))
    components = {c.name: c for c in signal.components}
    assert not components["volume"].available and not components["vwap"].available and not components["options"].available
    assert signal.coverage == pytest.approx(0.70)
    assert any("volume unavailable" in risk for risk in signal.risks)


def test_low_coverage_forces_no_trade():
    settings = RuntimeSettings()
    settings.signal.min_coverage = 0.95
    signal, *_ = analyse(make_ohlcv(400, drift=0.0012, vol=0.0008, volume=False, seed=5), settings)
    assert signal.label == LABEL_NO_TRADE and signal.plan is None and signal.direction == 0


def test_weights_are_configurable():
    settings = RuntimeSettings()
    settings.signal.weights = SignalWeights(trend=100, momentum=0, volume=0, ema_structure=0, vwap=0, market_structure=0,
                                            volatility=0, options=0)
    signal, *_ = analyse(make_ohlcv(400, drift=0.0012, vol=0.0008, seed=5), settings)
    trend = next(c for c in signal.components if c.name == "trend")
    assert signal.composite == pytest.approx(trend.score, abs=1e-3)
    assert signal.coverage == pytest.approx(1.0)


def test_options_component_uses_chain_metrics():
    frame = make_ohlcv(400, seed=9)
    bullish_chain = {"pcr_oi": 1.5, "call_oi_change": 1000.0, "put_oi_change": 9000.0, "call_wall": None, "put_wall": None}
    signal, *_ = analyse(frame, options=bullish_chain)
    options = next(c for c in signal.components if c.name == "options")
    assert options.available and options.score > 0 and any("PCR" in e for e in options.evidence)


def test_trade_plan_geometry():
    settings = RuntimeSettings()
    for direction, drift in ((1, 0.001), (-1, -0.001)):
        ind = compute_indicators(make_ohlcv(400, drift=drift, vol=0.0008, seed=5), settings.signal)
        levels = compute_levels(ind, True)
        plan = build_plan(direction, ind, levels, float(ind["atr"].iloc[-1]), settings.signal, settings.risk)
        assert plan is not None and plan.stop_basis and plan.target1_basis and plan.risk_reward > 0
        if direction > 0:
            assert plan.stop < plan.entry_low <= plan.entry_high < plan.target1 <= plan.target2
        else:
            assert plan.stop > plan.entry_high >= plan.entry_low > plan.target1 >= plan.target2


def test_swing_points_require_confirmation_bars():
    frame = make_ohlcv(120, seed=41)
    highs, lows = swing_points(frame, 3)
    assert all(frame.index.get_loc(ts) <= len(frame) - 4 for ts in [*highs.index, *lows.index])


def test_breakout_event_detected():
    frame = make_ohlcv(150, vol=0.0003, seed=42)
    prior_high = frame["high"].iloc[-21:-1].max()
    frame.iloc[-2, frame.columns.get_loc("close")] = min(frame["close"].iloc[-2], prior_high * 0.999)
    frame.iloc[-1, frame.columns.get_loc("close")] = prior_high * 1.004
    frame.iloc[-1, frame.columns.get_loc("high")] = prior_high * 1.005
    cfg = SignalSettings()
    ind = compute_indicators(frame, cfg)
    events = detect_events(ind, compute_levels(ind, True), cfg)
    breakout = [e for e in events if e.key == "breakout"]
    assert breakout and "volume_confirmed" in breakout[0].values


def test_confirmed_ema_cross_fires_exactly_once():
    close = np.concatenate([100 * np.exp(-0.002 * np.arange(80)), 100 * np.exp(-0.002 * 79) * np.exp(0.003 * np.arange(1, 41))])
    index = pd.date_range("2026-09-01 09:15", periods=len(close), freq="5min", tz=IST)
    frame = pd.DataFrame({"open": np.concatenate([[close[0]], close[:-1]]), "high": close * 1.001, "low": close * 0.999,
                          "close": close, "volume": 1000.0}, index=index)
    cfg = SignalSettings()
    ind = compute_indicators(frame, cfg)
    fired = 0
    for end in range(40, len(ind) + 1):
        window = ind.iloc[:end]
        fired += sum(e.key == "ema_cross_bull_confirmed" for e in detect_events(window, compute_levels(window, True), cfg))
    assert fired == 1


def test_regime_detection():
    strong = detect_regime(compute_indicators(make_ohlcv(300, drift=0.0015, vol=0.0005, seed=12), SignalSettings()))
    assert strong.direction == 1 and strong.code in ("STRONG_BULLISH_TREND", "WEAK_BULLISH_TREND", "BREAKOUT")
    assert strong.evidence
    short = detect_regime(compute_indicators(make_ohlcv(40, seed=13), SignalSettings()))
    assert short.code == "INSUFFICIENT_DATA"
