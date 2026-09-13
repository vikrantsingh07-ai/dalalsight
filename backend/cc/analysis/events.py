"""Technical state and event detection on completed bars.

Events carry a priority (LOW/MEDIUM/HIGH/CRITICAL) that drives commentary, voice and alerts.
Volume/VWAP events are only produced when the provider supplies real volume.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from ..config import SignalSettings
from .levels import LevelSet, swing_points


@dataclass
class TechEvent:
    key: str
    kind: str
    direction: int
    priority: str
    message: str
    bar_time: str
    values: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _f(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.2f}"


def technical_state(ind: pd.DataFrame, cfg: SignalSettings) -> dict:
    """Current indicator readings used by the UI, commentary and assistant."""
    last = ind.iloc[-1]
    close = float(last["close"])
    atr = _f(last.get("atr"))
    ema_fast, ema_slow = _f(last.get("ema_fast")), _f(last.get("ema_slow"))
    state: dict = {"close": close, "atr": atr, "atr_pct": _f(last.get("atr_pct"))}

    if ema_fast is not None and ema_slow is not None:
        diff = (ind["ema_fast"] - ind["ema_slow"]).dropna()
        cross_bars_ago = None
        signs = np.sign(diff.to_numpy())
        for back in range(1, min(len(signs), 30)):
            if signs[-back] != signs[-back - 1]:
                cross_bars_ago = back - 1
                break
        prior = _f(ind["ema_fast"].iloc[-4]) if len(ind) > 4 else None
        slope_pct = (ema_fast - prior) / prior * 100 / 3 if prior else None
        state["ema"] = {
            "fast": ema_fast, "slow": ema_slow, "fast_period": cfg.ema_fast, "slow_period": cfg.ema_slow,
            "relation": "bullish" if ema_fast > ema_slow else "bearish",
            "price_vs_fast": "above" if close > ema_fast else "below",
            "price_vs_slow": "above" if close > ema_slow else "below",
            "fast_slope_pct_per_bar": slope_pct,
            "distance_from_slow_pct": (close - ema_slow) / ema_slow * 100,
            "distance_from_slow_atr": (close - ema_slow) / atr if atr else None,
            "last_cross_bars_ago": cross_bars_ago,
            "cross_confirmed": cross_bars_ago is not None and cross_bars_ago >= cfg.crossover_confirm_bars - 1
            and ((close > max(ema_fast, ema_slow)) if ema_fast > ema_slow else (close < min(ema_fast, ema_slow))),
        }

    vwap = _f(last.get("vwap"))
    state["vwap"] = {"value": vwap, "relation": ("above" if close > vwap else "below")} if vwap else {
        "value": None, "relation": None, "unavailable_reason": "no real volume from the data provider (spot indices carry none)"}

    rsi = _f(last.get("rsi"))
    if rsi is not None:
        zone = "overbought" if rsi >= cfg.rsi_overbought else "oversold" if rsi <= cfg.rsi_oversold else "neutral"
        rsi_prev = _f(ind["rsi"].iloc[-4]) if len(ind) > 4 else None
        state["rsi"] = {"value": rsi, "zone": zone, "change_3_bars": None if rsi_prev is None else rsi - rsi_prev}

    hist = ind["macd_hist"].dropna()
    if len(hist) >= 4:
        h = hist.iloc[-4:].to_numpy()
        state["macd"] = {
            "macd": _f(last.get("macd")), "signal": _f(last.get("macd_signal")), "histogram": float(h[-1]),
            "relation": "bullish" if h[-1] > 0 else "bearish",
            "histogram_trend": "expanding" if abs(h[-1]) > abs(h[-2]) > abs(h[-3]) else "contracting" if abs(h[-1]) < abs(h[-2]) < abs(h[-3]) else "mixed",
        }

    if ind.attrs.get("has_volume") and _f(last.get("vol_sma")):
        prev_avg = _f(ind["vol_sma"].iloc[-2]) or _f(last.get("vol_sma"))
        state["volume"] = {"last": _f(last.get("volume")), "average20": prev_avg,
                           "ratio": (_f(last.get("volume")) or 0) / prev_avg if prev_avg else None}
    else:
        state["volume"] = {"unavailable_reason": "no real volume from the data provider"}

    atr_sma = _f(last.get("atr_sma"))
    state["volatility"] = {"atr": atr, "atr_ratio": atr / atr_sma if atr and atr_sma else None,
                           "bb_width": _f(last.get("bb_width")), "supertrend_dir": _f(last.get("supertrend_dir"))}
    state["adx"] = _f(last.get("adx"))
    return state


def detect_events(ind: pd.DataFrame, levels: LevelSet, cfg: SignalSettings, level_test_atr: float = 0.15) -> list[TechEvent]:
    if len(ind) < 30:
        return []
    events: list[TechEvent] = []
    cur, prev = ind.iloc[-1], ind.iloc[-2]
    bar_time = ind.index[-1].isoformat()
    close, atr = float(cur["close"]), _f(cur.get("atr")) or 0.0
    has_volume = bool(ind.attrs.get("has_volume"))

    def add(key: str, kind: str, direction: int, priority: str, message: str, **values) -> None:
        events.append(TechEvent(key, kind, direction, priority, message, bar_time, values))

    # EMA fast/slow crossover and confirmation
    f_now, s_now, f_prev, s_prev = (_f(cur.get("ema_fast")), _f(cur.get("ema_slow")), _f(prev.get("ema_fast")), _f(prev.get("ema_slow")))
    if f_now is not None and s_now is not None and f_prev is not None and s_prev is not None:
        if f_prev <= s_prev and f_now > s_now:
            add("ema_cross_bull", "ema_crossover", 1, "MEDIUM", f"Bullish EMA {cfg.ema_fast}/{cfg.ema_slow} crossover", fast=f_now, slow=s_now)
        elif f_prev >= s_prev and f_now < s_now:
            add("ema_cross_bear", "ema_crossover", -1, "MEDIUM", f"Bearish EMA {cfg.ema_fast}/{cfg.ema_slow} crossover", fast=f_now, slow=s_now)
        n = cfg.crossover_confirm_bars
        if len(ind) > n + 1:
            window = (ind["ema_fast"] - ind["ema_slow"]).iloc[-(n + 1):].to_numpy()
            # the cross happened exactly n bars ago and every bar since closed on the new side
            if window[0] <= 0 and (window[1:] > 0).all() and close > max(f_now, s_now):
                add("ema_cross_bull_confirmed", "ema_crossover_confirmed", 1, "HIGH",
                    f"Bullish EMA {cfg.ema_fast}/{cfg.ema_slow} crossover confirmed for {n} bars with price above both EMAs")
            if window[0] >= 0 and (window[1:] < 0).all() and close < min(f_now, s_now):
                add("ema_cross_bear_confirmed", "ema_crossover_confirmed", -1, "HIGH",
                    f"Bearish EMA {cfg.ema_fast}/{cfg.ema_slow} crossover confirmed for {n} bars with price below both EMAs")

    # VWAP (real volume only)
    vwap, vwap_prev = _f(cur.get("vwap")), _f(prev.get("vwap"))
    if has_volume and vwap and vwap_prev:
        buffer = 0.05 * atr
        prev_close = float(prev["close"])
        if prev_close < vwap_prev and close > vwap + buffer:
            add("vwap_breakout", "vwap_breakout", 1, "MEDIUM", f"Price reclaimed VWAP ({_fmt(vwap)})", vwap=vwap)
        elif prev_close > vwap_prev and close < vwap - buffer:
            add("vwap_breakdown", "vwap_breakdown", -1, "MEDIUM", f"Price lost VWAP ({_fmt(vwap)})", vwap=vwap)
        elif float(cur["high"]) > vwap and close < vwap and prev_close < vwap_prev:
            add("vwap_rejection_bear", "vwap_rejection", -1, "MEDIUM", f"VWAP rejection: high tested {_fmt(vwap)} and closed below", vwap=vwap)
        elif float(cur["low"]) < vwap and close > vwap and prev_close > vwap_prev:
            add("vwap_rejection_bull", "vwap_rejection", 1, "MEDIUM", f"VWAP held as support: low tested {_fmt(vwap)} and closed above", vwap=vwap)

    # RSI zones, momentum and divergence
    rsi, rsi_prev = _f(cur.get("rsi")), _f(prev.get("rsi"))
    if rsi is not None and rsi_prev is not None:
        if rsi_prev < cfg.rsi_overbought <= rsi:
            add("rsi_overbought", "rsi_overbought", 0, "MEDIUM", f"RSI entered overbought ({rsi:.1f})", rsi=rsi)
        if rsi_prev > cfg.rsi_oversold >= rsi:
            add("rsi_oversold", "rsi_oversold", 0, "MEDIUM", f"RSI entered oversold ({rsi:.1f})", rsi=rsi)
        if rsi_prev < 50 <= rsi:
            add("rsi_momentum_up", "rsi_momentum", 1, "LOW", f"RSI momentum turned positive (crossed 50, now {rsi:.1f})", rsi=rsi)
        if rsi_prev > 50 >= rsi:
            add("rsi_momentum_down", "rsi_momentum", -1, "LOW", f"RSI momentum turned negative (crossed 50, now {rsi:.1f})", rsi=rsi)
        events.extend(_divergence(ind, cfg, bar_time))

    # MACD
    hist = ind["macd_hist"].dropna()
    if len(hist) >= 4:
        h = hist.iloc[-4:].to_numpy()
        if h[-2] <= 0 < h[-1]:
            add("macd_cross_bull", "macd_crossover", 1, "MEDIUM", "Bullish MACD crossover (histogram turned positive)", histogram=float(h[-1]))
        elif h[-2] >= 0 > h[-1]:
            add("macd_cross_bear", "macd_crossover", -1, "MEDIUM", "Bearish MACD crossover (histogram turned negative)", histogram=float(h[-1]))
        elif abs(h[-1]) > abs(h[-2]) > abs(h[-3]):
            add("macd_hist_expanding", "macd_histogram", int(np.sign(h[-1])), "LOW", "MACD histogram expanding: momentum strengthening")
        elif abs(h[-1]) < abs(h[-2]) < abs(h[-3]):
            add("macd_hist_contracting", "macd_histogram", -int(np.sign(h[-1])), "LOW", "MACD histogram contracting: momentum fading")

    # Volume
    vol_avg = _f(prev.get("vol_sma"))
    volume = _f(cur.get("volume"))
    direction = 1 if close >= float(cur["open"]) else -1
    if has_volume and vol_avg and volume:
        ratio = volume / vol_avg
        if ratio >= cfg.volume_spike_mult:
            add("volume_spike", "volume_spike", direction, "MEDIUM", f"Volume spike: {ratio:.1f}× the 20-bar average", ratio=ratio)

    # Breakout / breakdown / false breakout
    if levels.breakout_level is not None and levels.breakdown_level is not None:
        prev_close = float(prev["close"])
        confirmed = has_volume and vol_avg and volume and volume / vol_avg >= cfg.volume_confirm_mult
        vol_text = " with volume confirmation" if confirmed else (" (volume unconfirmed)" if has_volume else " (no volume data)")
        if close > levels.breakout_level and prev_close <= levels.breakout_level:
            add("breakout", "breakout", 1, "HIGH", f"Breakout above {cfg.breakout_lookback}-bar high {_fmt(levels.breakout_level)}{vol_text}",
                level=levels.breakout_level, volume_confirmed=bool(confirmed))
        elif close < levels.breakdown_level and prev_close >= levels.breakdown_level:
            add("breakdown", "breakdown", -1, "HIGH", f"Breakdown below {cfg.breakout_lookback}-bar low {_fmt(levels.breakdown_level)}{vol_text}",
                level=levels.breakdown_level, volume_confirmed=bool(confirmed))
        if len(ind) > cfg.breakout_lookback + 3:
            prior_high = float(ind["high"].iloc[-(cfg.breakout_lookback + 2):-2].max())
            prior_low = float(ind["low"].iloc[-(cfg.breakout_lookback + 2):-2].min())
            if prev_close > prior_high and close < prior_high:
                add("false_breakout", "false_breakout", -1, "HIGH", f"Possible false breakout: price closed back below {_fmt(prior_high)}", level=prior_high)
            elif prev_close < prior_low and close > prior_low:
                add("false_breakdown", "false_breakdown", 1, "HIGH", f"Possible false breakdown: price closed back above {_fmt(prior_low)}", level=prior_low)

    # Support / resistance tests
    if atr:
        tol = level_test_atr * atr
        if levels.nearest_support and abs(float(cur["low"]) - levels.nearest_support.price) <= tol:
            add("support_test", "support_test", 1, "MEDIUM", f"Testing support {_fmt(levels.nearest_support.price)} ({levels.nearest_support.label})",
                level=levels.nearest_support.price)
        if levels.nearest_resistance and abs(float(cur["high"]) - levels.nearest_resistance.price) <= tol:
            add("resistance_test", "resistance_test", -1, "MEDIUM", f"Testing resistance {_fmt(levels.nearest_resistance.price)} ({levels.nearest_resistance.label})",
                level=levels.nearest_resistance.price)

    # Volatility regime shifts and squeezes
    atr_sma, atr_sma_prev = _f(cur.get("atr_sma")), _f(prev.get("atr_sma"))
    atr_prev = _f(prev.get("atr"))
    if atr and atr_sma and atr_prev and atr_sma_prev:
        if atr / atr_sma >= 1.3 > atr_prev / atr_sma_prev:
            add("volatility_expansion", "volatility_expansion", 0, "MEDIUM", f"Volatility expansion: ATR {atr / atr_sma:.2f}× its 20-bar average")
        elif atr / atr_sma <= 0.75 < atr_prev / atr_sma_prev:
            add("volatility_contraction", "volatility_contraction", 0, "LOW", f"Volatility contraction: ATR {atr / atr_sma:.2f}× its 20-bar average")
    width = ind["bb_width"].dropna()
    if len(width) >= 50 and width.iloc[-1] <= width.iloc[-50:].min() * 1.0001:
        add("consolidation", "consolidation", 0, "MEDIUM", "Consolidation: Bollinger Band width at a 50-bar low (squeeze)")

    st_now, st_prev = _f(cur.get("supertrend_dir")), _f(prev.get("supertrend_dir"))
    if st_now and st_prev and st_now != st_prev:
        add("supertrend_flip", "supertrend_flip", int(st_now), "MEDIUM", f"Supertrend flipped {'bullish' if st_now > 0 else 'bearish'}")

    # Sharp move: 3-bar move larger than 2.5 ATR
    if atr and len(ind) > 4:
        move = close - float(ind["close"].iloc[-4])
        if abs(move) >= 2.5 * atr:
            pct = move / float(ind["close"].iloc[-4]) * 100
            priority = "CRITICAL" if abs(pct) >= 1.0 else "HIGH"
            add("sharp_move_up" if move > 0 else "sharp_move_down", "sharp_move", int(np.sign(move)), priority,
                f"Sharp {'rally' if move > 0 else 'drop'} of {pct:+.2f}% over 3 bars ({abs(move) / atr:.1f} ATR)", pct=pct)
    return events


def _divergence(ind: pd.DataFrame, cfg: SignalSettings, bar_time: str) -> list[TechEvent]:
    """RSI divergence from the last two confirmed swings; reported only when the latest swing is recent."""
    recent = ind.tail(80)
    highs, lows = swing_points(recent, cfg.swing_lookback)
    out: list[TechEvent] = []
    fresh = 2 * cfg.swing_lookback + 2
    positions = {ts: i for i, ts in enumerate(recent.index)}
    if len(highs) >= 2:
        (t1, p1), (t2, p2) = list(highs.tail(2).items())
        r1, r2 = _f(recent.loc[t1, "rsi"]), _f(recent.loc[t2, "rsi"])
        if r1 and r2 and p2 > p1 and r2 < r1 and len(recent) - 1 - positions[t2] <= fresh:
            out.append(TechEvent("rsi_bear_divergence", "rsi_divergence", -1, "MEDIUM",
                                 f"Possible bearish RSI divergence: price higher high ({p2:,.2f} > {p1:,.2f}), RSI lower high ({r2:.1f} < {r1:.1f})",
                                 bar_time, {}))
    if len(lows) >= 2:
        (t1, p1), (t2, p2) = list(lows.tail(2).items())
        r1, r2 = _f(recent.loc[t1, "rsi"]), _f(recent.loc[t2, "rsi"])
        if r1 and r2 and p2 < p1 and r2 > r1 and len(recent) - 1 - positions[t2] <= fresh:
            out.append(TechEvent("rsi_bull_divergence", "rsi_divergence", 1, "MEDIUM",
                                 f"Possible bullish RSI divergence: price lower low ({p2:,.2f} < {p1:,.2f}), RSI higher low ({r2:.1f} > {r1:.1f})",
                                 bar_time, {}))
    return out
