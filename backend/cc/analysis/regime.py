"""Market regime engine (rule-based, transparent evidence)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

REGIME_LABELS = {
    "STRONG_BULLISH_TREND": "Strong bullish trend",
    "WEAK_BULLISH_TREND": "Weak bullish trend",
    "STRONG_BEARISH_TREND": "Strong bearish trend",
    "WEAK_BEARISH_TREND": "Weak bearish trend",
    "RANGE_BOUND": "Range-bound",
    "HIGH_VOLATILITY": "High volatility",
    "LOW_VOLATILITY": "Low volatility",
    "BREAKOUT": "Breakout regime",
    "TRANSITION": "Transition regime",
    "INSUFFICIENT_DATA": "Insufficient data",
}


@dataclass
class Regime:
    code: str
    label: str
    direction: int
    volatility: str  # high | normal | low | unknown
    adx: float | None
    atr_pct: float | None
    atr_percentile: float | None
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _f(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def detect_regime(ind: pd.DataFrame, breadth: dict | None = None) -> Regime:
    if len(ind) < 60 or _f(ind["ema50"].iloc[-1]) is None:
        return Regime("INSUFFICIENT_DATA", REGIME_LABELS["INSUFFICIENT_DATA"], 0, "unknown", None, None, None,
                      [f"needs at least 60 bars with indicators; have {len(ind)}"])
    last = ind.iloc[-1]
    close = float(last["close"])
    ema20, ema50 = float(last["ema20"]), float(last["ema50"])
    ema20_prev = _f(ind["ema20"].iloc[-6])
    slope20 = (ema20 - ema20_prev) / ema20_prev * 100 if ema20_prev else 0.0
    adx = _f(last.get("adx"))
    atr_pct = _f(last.get("atr_pct"))
    history = ind["atr_pct"].dropna().tail(100)
    atr_percentile = float((history <= atr_pct).mean() * 100) if atr_pct is not None and len(history) >= 20 else None
    volatility = "unknown" if atr_percentile is None else "high" if atr_percentile >= 85 else "low" if atr_percentile <= 15 else "normal"

    evidence = [
        f"close {close:,.2f} vs EMA20 {ema20:,.2f} / EMA50 {ema50:,.2f}",
        f"EMA20 slope {slope20:+.3f}% over 5 bars",
        f"ADX {adx:.1f}" if adx is not None else "ADX unavailable",
        f"ATR {atr_pct:.2f}% of price (percentile {atr_percentile:.0f} of last 100 bars)" if atr_percentile is not None else "ATR percentile unavailable",
    ]

    direction = 0
    if close > ema20 > ema50 and slope20 > 0:
        direction = 1
    elif close < ema20 < ema50 and slope20 < 0:
        direction = -1

    prior = ind.iloc[-21:-1]
    atr_now, atr_avg = _f(last.get("atr")), _f(last.get("atr_sma"))
    atr_ratio = atr_now / atr_avg if atr_now and atr_avg else None
    breakout_dir = 0
    if len(prior) == 20:
        if close > float(prior["high"].max()):
            breakout_dir = 1
        elif close < float(prior["low"].min()):
            breakout_dir = -1
    if breakout_dir and atr_ratio is not None:
        evidence.append(f"close outside the prior 20-bar range; ATR {atr_ratio:.2f}× average")

    if breadth and breadth.get("advances") is not None and breadth.get("declines") is not None:
        adv, dec = breadth["advances"], breadth["declines"]
        if adv + dec > 0:
            evidence.append(f"breadth {adv:.0f} advances / {dec:.0f} declines ({adv / (adv + dec) * 100:.0f}% advancing)")

    crossed_recently = False
    diff = (ind["ema_fast"] - ind["ema_slow"]).dropna().tail(6)
    if len(diff) == 6:
        crossed_recently = bool((np.sign(diff.to_numpy()[1:]) != np.sign(diff.to_numpy()[:-1])).any())

    if breakout_dir and atr_ratio is not None and atr_ratio >= 1.1:
        code, direction = "BREAKOUT", breakout_dir
    elif direction != 0 and adx is not None and adx >= 25:
        code = "STRONG_BULLISH_TREND" if direction > 0 else "STRONG_BEARISH_TREND"
    elif direction != 0 and adx is not None and adx >= 18:
        code = "WEAK_BULLISH_TREND" if direction > 0 else "WEAK_BEARISH_TREND"
    elif volatility == "high" and direction == 0:
        code = "HIGH_VOLATILITY"
    elif volatility == "low" and (adx is None or adx < 18):
        code = "LOW_VOLATILITY"
    elif adx is not None and adx < 20 and not crossed_recently:
        code = "RANGE_BOUND"
    else:
        code = "TRANSITION"
        if crossed_recently:
            evidence.append("EMA fast/slow crossed within the last 5 bars")
    return Regime(code, REGIME_LABELS[code], direction, volatility, adx, atr_pct, atr_percentile, evidence)
