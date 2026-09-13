"""Stock scanner and stock scoring (transparent, rule-based).

Metrics come from daily OHLCV. Every score is a checklist whose individual criteria are returned,
and fundamentals come from the vendor feed and are marked unavailable when not published.
Scores rank evidence; they are not recommendations.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from ..config import SignalSettings
from .indicators import compute_indicators


def _f(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _ret(close: pd.Series, bars: int) -> float | None:
    if len(close) <= bars:
        return None
    return float(close.iloc[-1] / close.iloc[-1 - bars] - 1) * 100


def _gt(a, b) -> bool | None:
    return None if a is None or b is None else a > b


def compute_stock_metrics(daily: pd.DataFrame, bench_close: pd.Series | None, cfg: SignalSettings) -> dict:
    """Daily metrics used by the scanner, stock analysis and presets. Needs ≥ 60 daily bars."""
    if len(daily) < 60:
        return {"insufficient": True, "bars": len(daily)}
    ind = compute_indicators(daily, cfg, intraday=False)
    close, volume = ind["close"], ind["volume"]
    last = ind.iloc[-1]
    price = float(last["close"])
    has_volume = bool(ind.attrs.get("has_volume"))
    high_52w = float(ind["high"].tail(252).max())
    low_52w = float(ind["low"].tail(252).min())

    metrics: dict = {
        "insufficient": False,
        "bars": len(ind),
        "last_date": ind.index[-1].date().isoformat(),
        "close": price,
        "change_pct": _ret(close, 1),
        "ret_5d": _ret(close, 5),
        "ret_20d": _ret(close, 20),
        "ret_60d": _ret(close, 60),
        "ret_120d": _ret(close, 120),
        "ret_250d": _ret(close, 250),
        "ema_fast": _f(last["ema_fast"]),
        "ema_slow": _f(last["ema_slow"]),
        "ema20": _f(last["ema20"]),
        "ema50": _f(last["ema50"]),
        "sma200": _f(last["sma200"]),
        "rsi": _f(last["rsi"]),
        "adx": _f(last["adx"]),
        "atr_pct": _f(last["atr_pct"]),
        "macd_hist": _f(last["macd_hist"]),
        "supertrend_dir": _f(last["supertrend_dir"]),
        "high_20_prior": float(ind["high"].iloc[-21:-1].max()),
        "low_20_prior": float(ind["low"].iloc[-21:-1].min()),
        "high_52w": high_52w,
        "low_52w": low_52w,
        "dist_52w_high_pct": (price / high_52w - 1) * 100,
        "dist_52w_low_pct": (price / low_52w - 1) * 100,
        "has_volume": has_volume,
    }

    rsi_recent = ind["rsi"].tail(4).to_numpy()
    metrics["rsi_crossed_up_30"] = bool(len(rsi_recent) == 4 and np.nanmin(rsi_recent[:-1]) < cfg.rsi_oversold <= rsi_recent[-1])
    metrics["rsi_crossed_down_70"] = bool(len(rsi_recent) == 4 and np.nanmax(rsi_recent[:-1]) > cfg.rsi_overbought >= rsi_recent[-1])

    diff = (ind["ema_fast"] - ind["ema_slow"]).tail(4).to_numpy()
    cross, cross_ago = 0, None
    for back in range(1, 4):
        if np.sign(diff[-back]) != np.sign(diff[-back - 1]):
            cross, cross_ago = int(np.sign(diff[-back])), back - 1
            break
    metrics["ema_cross"], metrics["ema_cross_bars_ago"] = cross, cross_ago

    if has_volume:
        prior_avg = _f(volume.iloc[-21:-1].mean())
        metrics["volume"] = _f(last["volume"])
        metrics["vol_ratio"] = (_f(last["volume"]) or 0) / prior_avg if prior_avg else None
        avg50 = _f(volume.tail(50).mean())
        avg5 = _f(volume.tail(5).mean())
        metrics["vol_ratio_5_50"] = avg5 / avg50 if avg5 is not None and avg50 else None
        metrics["avg_traded_value_cr"] = _f((close * volume).tail(20).mean() / 1e7)
        recent = ind.tail(20)
        up = recent.loc[recent["close"] >= recent["close"].shift(1), "volume"].sum()
        down = recent.loc[recent["close"] < recent["close"].shift(1), "volume"].sum()
        metrics["updown_volume_ratio"] = float(up / down) if down > 0 else None
    else:
        metrics.update({"volume": None, "vol_ratio": None, "vol_ratio_5_50": None, "avg_traded_value_cr": None, "updown_volume_ratio": None})

    if bench_close is not None and len(bench_close) > 60:
        bench = pd.Series(bench_close.to_numpy(dtype=float), index=pd.Index(bench_close.index.date))
        bench = bench[~bench.index.duplicated(keep="last")]
        stock = pd.Series(close.to_numpy(dtype=float), index=pd.Index(ind.index.date))
        stock = stock[~stock.index.duplicated(keep="last")]
        common = stock.index.intersection(bench.index)
        s, b = stock.loc[common], bench.loc[common]
        for bars in (20, 60, 120):
            sr, br = _ret(s, bars), _ret(b, bars)
            metrics[f"rs_{bars}"] = None if sr is None or br is None else sr - br
    else:
        metrics.update({"rs_20": None, "rs_60": None, "rs_120": None})
    return metrics


def _checklist(name: str, weight: float, checks: list[tuple[str, bool | None]]) -> dict:
    available = [(label, ok) for label, ok in checks if ok is not None]
    passed = sum(1 for _, ok in available if ok)
    return {
        "name": name,
        "weight": weight,
        "available": bool(available),
        "score": round(passed / len(available) * 100, 1) if available else None,
        "criteria": [{"label": label, "passed": ok} for label, ok in checks],
    }


def score_stock(m: dict, fundamentals: dict | None = None) -> dict:
    if m.get("insufficient"):
        return {"total": None, "rating": "Insufficient data", "components": [], "note": f"only {m.get('bars')} daily bars"}
    close = m["close"]
    components = [
        _checklist("trend", 25, [
            ("Close above EMA 20", _gt(close, m["ema20"])),
            ("EMA 20 above EMA 50", _gt(m["ema20"], m["ema50"])),
            ("Close above SMA 200", _gt(close, m["sma200"])),
            ("ADX ≥ 20 (trend strength)", None if m["adx"] is None else m["adx"] >= 20),
            ("Supertrend bullish", None if m["supertrend_dir"] is None else m["supertrend_dir"] > 0),
        ]),
        _checklist("momentum", 20, [
            ("RSI between 50 and 75", None if m["rsi"] is None else 50 <= m["rsi"] <= 75),
            ("MACD histogram positive", None if m["macd_hist"] is None else m["macd_hist"] > 0),
            ("20-day return positive", None if m["ret_20d"] is None else m["ret_20d"] > 0),
            ("60-day return positive", None if m["ret_60d"] is None else m["ret_60d"] > 0),
        ]),
        _checklist("relative_strength", 20, [
            ("Outperformed NIFTY 50 over 20 days", None if m.get("rs_20") is None else m["rs_20"] > 0),
            ("Outperformed NIFTY 50 over 60 days", None if m.get("rs_60") is None else m["rs_60"] > 0),
            ("Outperformed NIFTY 50 over 120 days", None if m.get("rs_120") is None else m["rs_120"] > 0),
        ]),
        _checklist("volume", 10, [
            ("5-day volume above 50-day average", None if m["vol_ratio_5_50"] is None else m["vol_ratio_5_50"] > 1),
            ("Up-day volume exceeds down-day volume (20 days)", None if m["updown_volume_ratio"] is None else m["updown_volume_ratio"] > 1),
        ]),
        _checklist("risk", 10, [
            ("ATR ≤ 2.5% of price", None if m["atr_pct"] is None else m["atr_pct"] <= 2.5),
            ("Within 15% of the 52-week high", m["dist_52w_high_pct"] >= -15),
            ("Average traded value ≥ ₹10 crore/day", None if m["avg_traded_value_cr"] is None else m["avg_traded_value_cr"] >= 10),
        ]),
    ]
    f = fundamentals or {}
    components.append(_checklist("fundamentals", 15, [
        ("Return on equity ≥ 15%", None if f.get("returnOnEquity") is None else f["returnOnEquity"] >= 0.15),
        ("Debt/equity ≤ 1.0", None if f.get("debtToEquity") is None else f["debtToEquity"] <= 100),
        ("Revenue growth ≥ 10% (vendor, latest reported)", None if f.get("revenueGrowth") is None else f["revenueGrowth"] >= 0.10),
        ("Earnings growth positive", None if f.get("earningsGrowth") is None else f["earningsGrowth"] > 0),
        ("Net profit margin ≥ 10%", None if f.get("profitMargins") is None else f["profitMargins"] >= 0.10),
        ("Trailing P/E between 0 and 40", None if f.get("trailingPE") is None else 0 < f["trailingPE"] <= 40),
    ]))
    available = [c for c in components if c["available"]]
    weight = sum(c["weight"] for c in available)
    total = round(sum(c["weight"] * c["score"] for c in available) / weight, 1) if weight else None
    rating = (
        "Insufficient data" if total is None else "Strong" if total >= 70 else "Positive" if total >= 55
        else "Neutral" if total >= 45 else "Weak" if total >= 30 else "Poor"
    )
    missing = [c["name"] for c in components if not c["available"]]
    return {
        "total": total,
        "rating": rating,
        "components": components,
        "coverage": round(weight / sum(c["weight"] for c in components), 3),
        "missing": missing,
        "method": "weighted share of passed criteria per component, over components with data",
        "note": "Rule-based evidence score, not a recommendation.",
    }


def _ge(value, threshold) -> bool:
    return value is not None and value >= threshold


def _le(value, threshold) -> bool:
    return value is not None and value <= threshold


Predicate = Callable[[dict], bool]

PRESETS: dict[str, tuple[str, str, Predicate]] = {
    "breakout": ("Breakout with volume", "Close above the prior 20-day high on at least 1.5× average volume",
                 lambda m: _gt(m["close"], m["high_20_prior"]) is True and _ge(m["vol_ratio"], 1.5)),
    "breakdown": ("Breakdown with volume", "Close below the prior 20-day low on at least 1.5× average volume",
                  lambda m: _gt(m["low_20_prior"], m["close"]) is True and _ge(m["vol_ratio"], 1.5)),
    "momentum": ("Momentum leaders", "RSI 55–75, close > EMA 20 > EMA 50, positive 20-day return and relative strength",
                 lambda m: _ge(m["rsi"], 55) and _le(m["rsi"], 75) and _gt(m["close"], m["ema20"]) is True
                 and _gt(m["ema20"], m["ema50"]) is True and _ge(m["ret_20d"], 0) and _ge(m.get("rs_20"), 0)),
    "oversold_bounce": ("Oversold bounce", "RSI crossed back above the oversold threshold in the last 3 sessions",
                        lambda m: bool(m["rsi_crossed_up_30"])),
    "ema_bullish_cross": ("Bullish EMA crossover", "Fast EMA crossed above slow EMA in the last 3 sessions",
                          lambda m: m["ema_cross"] == 1),
    "ema_bearish_cross": ("Bearish EMA crossover", "Fast EMA crossed below slow EMA in the last 3 sessions",
                          lambda m: m["ema_cross"] == -1),
    "volume_spike": ("Volume spike", "Latest session volume at least 2× the prior 20-day average",
                     lambda m: _ge(m["vol_ratio"], 2.0)),
    "near_52w_high": ("Near 52-week high", "Close within 3% of the 52-week high",
                      lambda m: m["dist_52w_high_pct"] >= -3),
    "near_52w_low": ("Near 52-week low", "Close within 3% of the 52-week low",
                     lambda m: m["dist_52w_low_pct"] <= 3),
    "strong_trend": ("Strong uptrend", "ADX ≥ 25 with close > EMA 20 > EMA 50 > SMA 200",
                     lambda m: _ge(m["adx"], 25) and _gt(m["close"], m["ema20"]) is True and _gt(m["ema20"], m["ema50"]) is True
                     and _gt(m["ema50"], m["sma200"]) is True),
    "relative_strength": ("Relative strength leaders", "Outperforming NIFTY 50 over both 20 and 60 sessions by at least 3 points",
                          lambda m: _ge(m.get("rs_20"), 3) and _ge(m.get("rs_60"), 3)),
}


def run_preset(metrics_by_symbol: dict[str, dict], preset: str) -> list[str]:
    if preset not in PRESETS:
        raise ValueError(f"unknown scanner preset {preset!r}")
    predicate = PRESETS[preset][2]
    return [symbol for symbol, m in metrics_by_symbol.items() if not m.get("insufficient") and predicate(m)]
