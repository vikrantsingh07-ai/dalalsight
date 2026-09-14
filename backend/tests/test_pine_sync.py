"""The TradingView indicator mirrors the dashboard engine: same default weights, thresholds, periods and labels."""

import re

from cc.analysis import signal_engine
from cc.config import PROJECT_ROOT, RiskSettings, SignalSettings

PINE = PROJECT_ROOT / "tradingview" / "dalalsight_signal_engine.pine"

# Pine input variable -> SignalSettings attribute
PINE_INPUTS = {
    "wTrend": "weights.trend", "wMom": "weights.momentum", "wVol": "weights.volume", "wEma": "weights.ema_structure",
    "wVwap": "weights.vwap", "wStruct": "weights.market_structure", "wVola": "weights.volatility", "wOpt": "weights.options",
    "bullTh": "bullish_threshold", "bearTh": "bearish_threshold", "watchBand": "watch_band", "minConf": "min_confidence",
    "minCov": "min_coverage", "minRR": "min_risk_reward", "emaFastLen": "ema_fast", "emaSlowLen": "ema_slow",
    "confirmBars": "crossover_confirm_bars", "rsiLen": "rsi_period", "rsiOB": "rsi_overbought", "rsiOS": "rsi_oversold",
    "atrLen": "atr_period", "stLen": "supertrend_period", "stMult": "supertrend_mult", "swingLb": "swing_lookback",
    "breakoutLb": "breakout_lookback", "volSpike": "volume_spike_mult", "volConfirm": "volume_confirm_mult",
}


def pine_defaults() -> dict[str, float]:
    text = PINE.read_text(encoding="utf-8")
    return {name: float(value) for name, value in re.findall(r"^(\w+) = input\.(?:float|int)\(([-\d.]+)", text, re.MULTILINE)}


def test_pine_defaults_match_the_engine():
    defaults = pine_defaults()
    settings = SignalSettings()
    for variable, path in PINE_INPUTS.items():
        value = settings
        for part in path.split("."):
            value = getattr(value, part)
        assert defaults[variable] == float(value), f"Pine {variable} = {defaults[variable]}, engine {path} = {value}"
    assert defaults["maxStopAtr"] == RiskSettings().max_stop_atr


def test_pine_uses_the_engine_labels():
    text = PINE.read_text(encoding="utf-8")
    for label in (signal_engine.LABEL_BULL, signal_engine.LABEL_BEAR, signal_engine.LABEL_WATCH, signal_engine.LABEL_NO_TRADE,
                  signal_engine.LABEL_HIGH_RISK, signal_engine.LABEL_LOW_QUALITY):
        assert f'"{label}"' in text, label
    assert "CC Signal Engine" not in text
