"""Walk-forward backtest of the signal engine, calibration of its stated probabilities, and outcome tracking for
recorded signals.

No look-ahead: at each bar close the engine only sees bars up to that close (indicators are
causal; levels, events, regime and the signal are rebuilt on a trailing window ending at that
bar). Entries follow the signal's plan: a limit order at the entry-zone midpoint is placed at the
signal bar's close and is valid for a few bars (filled at the better of the bar open and the limit,
plus slippage); unfilled orders expire. When one bar touches both the stop and the target, the stop
is assumed to fill first. R multiples use the planned risk (limit to stop). Results are historical
simulations, not forecasts.

Calibration asks whether the engine's "bullish scenario %" means what it says: at every evaluated bar it records
the stated percentage, then checks which came first in the following bars, a move of +1 ATR or −1 ATR. A calibrated
engine shows about 65% "up first" among the bars where it stated 65%.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from ..config import RuntimeSettings
from .events import detect_events
from .indicators import compute_indicators
from .levels import compute_levels
from .regime import detect_regime
from .signal_engine import LABEL_BEAR, LABEL_BULL, build_signal

CALIBRATION_TOUCH_ATR = 1.0
MIN_RESOLVED = 30  # buckets with fewer resolved bars are too noisy to judge
BULLISH_BUCKETS = [(0.0, 35.0, "0–35"), (35.0, 42.0, "35–42"), (42.0, 50.0, "42–50"), (50.0, 58.0, "50–58"),
                   (58.0, 65.0, "58–65"), (65.0, 100.01, "65–100")]
CONFIDENCE_BUCKETS = [(0.0, 25.0, "0–25"), (25.0, 40.0, "25–40"), (40.0, 55.0, "40–55"), (55.0, 100.01, "55–100")]


class BacktestParams(BaseModel):
    symbol: str = Field("NIFTY", max_length=32)
    timeframe: str = "15m"
    bars: int = Field(1200, ge=200, le=3000)
    window: int = Field(300, ge=120, le=600)
    warmup: int = Field(120, ge=60, le=500)
    max_hold_bars: int = Field(30, ge=1, le=300)
    slippage_bps: float = Field(2.0, ge=0, le=100)
    cost_pct_per_side: float = Field(0.03, ge=0, le=1)
    target: Literal["T1", "T2"] = "T1"
    labels: list[str] = Field(default_factory=lambda: [LABEL_BULL, LABEL_BEAR])
    square_off_intraday: bool = True
    entry_window_bars: int = Field(5, ge=1, le=50)


def run_backtest(frame: pd.DataFrame, params: BacktestParams, settings: RuntimeSettings, intraday: bool,
                 progress: Callable[[float], None] | None = None) -> dict:
    cfg = settings.signal
    ind = compute_indicators(frame, cfg, intraday)
    n = len(ind)
    if n < params.warmup + 20:
        raise ValueError(f"need at least {params.warmup + 20} bars, have {n}")
    slip = params.slippage_bps / 10000
    trades: list[dict] = []
    labels: Counter[str] = Counter()
    samples: list[dict] = []
    skipped_gaps = 0
    unfilled = 0
    position: dict | None = None
    pending: dict | None = None
    dates = ind.index.date
    allowed = set(params.labels)
    square_off = intraday and params.square_off_intraday

    for i in range(params.warmup, n):
        bar = ind.iloc[i]
        session_end = square_off and i + 1 < n and dates[i + 1] != dates[i]
        if pending is not None:
            if i > pending["expires"] or (square_off and dates[i] != pending["date"]):
                unfilled += 1
                pending = None
            else:
                position, gapped = _try_fill(pending, bar, i, ind.index[i], slip)
                if position is not None or gapped:
                    skipped_gaps += int(gapped)
                    pending = None
        if position is not None:
            exit_info = _check_exit(position, bar, i, n, params, session_end)
            if exit_info:
                price, reason = exit_info
                trades.append(_close_trade(position, price * (1 - position["direction"] * slip), reason, ind.index[i], i, params))
                position = None
        if i < n - 1:
            # the signal is evaluated at every bar (for calibration); orders are only placed when flat
            window = ind.iloc[max(0, i - params.window + 1): i + 1]
            levels = compute_levels(window, intraday, cfg.swing_lookback, cfg.breakout_lookback)
            events = detect_events(window, levels, cfg, settings.commentary.level_test_atr)
            regime = detect_regime(window)
            signal = build_signal(params.symbol, params.timeframe, window, events, levels, regime, None, cfg, settings.risk, ["backtest"])
            labels[signal.label] += 1
            samples.append({"i": i, "bullish_pct": signal.bullish_pct, "confidence": signal.model_confidence,
                            "label": signal.label, "direction": signal.direction})
            # never place a new intraday order on the session's last bar (it could only fill tomorrow)
            if position is None and pending is None and signal.label in allowed and signal.plan is not None and not session_end:
                plan = signal.plan
                pending = {
                    "direction": plan.direction, "limit": (plan.entry_low + plan.entry_high) / 2, "stop": plan.stop,
                    "target": plan.target1 if params.target == "T1" else plan.target2, "label": signal.label,
                    "signal_time": ind.index[i], "expires": i + params.entry_window_bars, "date": dates[i],
                    "confidence": signal.model_confidence, "bullish_pct": signal.bullish_pct,
                }
        if progress and i % 50 == 0:
            progress((i - params.warmup) / max(1, n - params.warmup))
    if pending is not None:
        unfilled += 1
    if position is not None:
        trades.append(_close_trade(position, float(ind["close"].iloc[-1]), "end of data", ind.index[-1], n - 1, params))
    summary = summarize(trades, labels, skipped_gaps, ind, params, unfilled)
    summary["calibration"] = calibrate(ind, samples, params.max_hold_bars, square_off)
    return {"summary": summary, "trades": trades}


def _try_fill(pending: dict, bar: pd.Series, i: int, ts: pd.Timestamp, slip: float) -> tuple[dict | None, bool]:
    """Fill the plan's limit order on this bar. Returns (position, opened_through_stop)."""
    d, limit, stop = pending["direction"], pending["limit"], pending["stop"]
    o, h, low = float(bar["open"]), float(bar["high"]), float(bar["low"])
    if d > 0:
        if low > limit:
            return None, False
        fill = min(o, limit)
        if fill <= stop:
            return None, True
    else:
        if h < limit:
            return None, False
        fill = max(o, limit)
        if fill >= stop:
            return None, True
    return {
        "direction": d, "entry": fill * (1 + d * slip), "stop": stop, "target": pending["target"], "label": pending["label"],
        "entry_index": i, "entry_time": ts, "signal_time": pending["signal_time"], "risk": abs(limit - stop),
        "confidence": pending["confidence"], "bullish_pct": pending["bullish_pct"], "mfe": 0.0, "mae": 0.0,
    }, False


def _check_exit(position: dict, bar: pd.Series, i: int, n: int, params: BacktestParams, session_end: bool) -> tuple[float, str] | None:
    d, stop, target = position["direction"], position["stop"], position["target"]
    o, h, low, c = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])
    favourable = (h - position["entry"]) if d > 0 else (position["entry"] - low)
    adverse = (position["entry"] - low) if d > 0 else (h - position["entry"])
    position["mfe"] = max(position["mfe"], favourable)
    position["mae"] = max(position["mae"], adverse)
    if i > position["entry_index"]:
        if (d > 0 and o <= stop) or (d < 0 and o >= stop):
            return o, "stop (gap)"
        if (d > 0 and o >= target) or (d < 0 and o <= target):
            return o, "target (gap)"
    if (d > 0 and low <= stop) or (d < 0 and h >= stop):
        return stop, "stop"
    if (d > 0 and h >= target) or (d < 0 and low <= target):
        return target, "target"
    if i - position["entry_index"] + 1 >= params.max_hold_bars:
        return c, "time exit"
    if session_end:
        return c, "session square-off"
    if i == n - 1:
        return c, "end of data"
    return None


def _close_trade(position: dict, exit_price: float, reason: str, exit_time, exit_index: int, params: BacktestParams) -> dict:
    d, entry, risk = position["direction"], position["entry"], position["risk"]
    cost_points = (entry + exit_price) * params.cost_pct_per_side / 100
    r_multiple = (d * (exit_price - entry) - cost_points) / risk if risk > 0 else 0.0
    return {
        "label": position["label"],
        "direction": d,
        "signal_time": position["signal_time"].isoformat(),
        "entry_time": position["entry_time"].isoformat(),
        "exit_time": exit_time.isoformat(),
        "entry": round(entry, 2),
        "exit": round(exit_price, 2),
        "stop": position["stop"],
        "target": position["target"],
        "bars_held": exit_index - position["entry_index"] + 1,
        "reason": reason,
        "r_multiple": round(r_multiple, 3),
        "pnl_pct": round((d * (exit_price - entry) / entry - 2 * params.cost_pct_per_side / 100) * 100, 3),
        "mfe_r": round(position["mfe"] / risk, 3) if risk > 0 else None,
        "mae_r": round(position["mae"] / risk, 3) if risk > 0 else None,
        "confidence": position["confidence"],
    }


def summarize(trades: list[dict], labels: Counter, skipped_gaps: int, ind: pd.DataFrame, params: BacktestParams,
              unfilled: int = 0) -> dict:
    r = np.array([t["r_multiple"] for t in trades], dtype=float)
    wins, losses = r[r > 0], r[r <= 0]
    equity = np.cumsum(r) if len(r) else np.array([0.0])
    drawdown = float((np.maximum.accumulate(np.concatenate([[0.0], equity])) - np.concatenate([[0.0], equity])).max())
    by_label = {}
    for label in {t["label"] for t in trades}:
        rs = np.array([t["r_multiple"] for t in trades if t["label"] == label])
        by_label[label] = {"trades": len(rs), "win_rate": round(float((rs > 0).mean() * 100), 1), "avg_r": round(float(rs.mean()), 3)}
    return {
        "symbol": params.symbol,
        "timeframe": params.timeframe,
        "period": {"start": ind.index[0].isoformat(), "end": ind.index[-1].isoformat(), "bars": len(ind)},
        "trades": len(trades),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate": round(float(len(wins) / len(r) * 100), 1) if len(r) else None,
        "avg_r": round(float(r.mean()), 3) if len(r) else None,
        "expectancy_r": round(float(r.mean()), 3) if len(r) else None,
        "total_r": round(float(r.sum()), 3) if len(r) else 0.0,
        "profit_factor": round(float(wins.sum() / -losses.sum()), 3) if len(losses) and losses.sum() < 0 else None,
        "max_drawdown_r": round(drawdown, 3),
        "avg_bars_held": round(float(np.mean([t["bars_held"] for t in trades])), 1) if trades else None,
        "exit_reasons": dict(Counter(t["reason"] for t in trades)),
        "by_label": by_label,
        "signal_label_counts": dict(labels),
        "skipped_gap_entries": skipped_gaps,
        "entries_not_filled": unfilled,
        "equity_curve_r": [round(float(x), 3) for x in equity],
        "assumptions": [
            "signal evaluated at bar close using only bars up to that close",
            f"entry: limit at the plan's entry-zone midpoint valid {params.entry_window_bars} bars (better of open/limit) plus slippage; exits at stop/target minus slippage",
            "R multiples measured against planned risk (limit to stop)",
            "stop assumed first when a bar touches both stop and target",
            f"costs {params.cost_pct_per_side}% per side; slippage {params.slippage_bps} bps",
            "options component excluded (no historical option chains)",
            "signal label counts cover every evaluated bar, including bars when a trade was already open",
        ],
    }


# ---------------------------------------------------------------------------- calibration
def calibrate(ind: pd.DataFrame, samples: list[dict], horizon: int, same_session: bool) -> dict:
    """Compare the engine's stated bullish % and confidence with what price did next (see the module docstring)."""
    high, low, close = (ind[c].to_numpy(dtype=float) for c in ("high", "low", "close"))
    atr = ind["atr"].to_numpy(dtype=float)
    dates = ind.index.date
    n = len(ind)
    rows: list[dict] = []
    for sample in samples:
        i = sample["i"]
        unit = atr[i]
        if not np.isfinite(unit) or unit <= 0:
            continue
        end = i
        while end + 1 < n and end + 1 <= i + horizon and not (same_session and dates[end + 1] != dates[i]):
            end += 1
        if end == i:
            continue  # no later bar to judge (last bar of a session or of the data)
        up, down = close[i] + CALIBRATION_TOUCH_ATR * unit, close[i] - CALIBRATION_TOUCH_ATR * unit
        outcome = "neither"
        for j in range(i + 1, end + 1):
            hit_up, hit_down = high[j] >= up, low[j] <= down
            if hit_up and hit_down:
                outcome = "ambiguous"
                break
            if hit_up or hit_down:
                outcome = "up" if hit_up else "down"
                break
        rows.append({**sample, "outcome": outcome, "forward_atr": (close[end] - close[i]) / unit})

    by_bullish = [_bucket_stats(name, [r for r in rows if lo <= r["bullish_pct"] < hi]) for lo, hi, name in BULLISH_BUCKETS]
    judged = [b for b in by_bullish if b["observed_up_pct"] is not None and b["up_first"] + b["down_first"] >= MIN_RESOLVED]
    weight = sum(b["up_first"] + b["down_first"] for b in judged)
    gap = sum(abs(b["observed_up_pct"] - b["stated_bullish_pct"]) * (b["up_first"] + b["down_first"]) for b in judged) / weight if weight else None
    directional = [r for r in rows if r["direction"]]
    return {
        "samples": len(rows),
        "horizon_bars": horizon,
        "touch_atr": CALIBRATION_TOUCH_ATR,
        "mean_abs_gap_pts": round(gap, 1) if gap is not None else None,
        "by_bullish_pct": by_bullish,
        "by_label": [_bucket_stats(label, [r for r in rows if r["label"] == label]) for label in sorted({r["label"] for r in rows})],
        "by_confidence": [_bucket_stats(name, [r for r in directional if lo <= r["confidence"] < hi]) for lo, hi, name in CONFIDENCE_BUCKETS],
        "method": (f"At every evaluated bar: did price touch +{CALIBRATION_TOUCH_ATR:g} ATR or −{CALIBRATION_TOUCH_ATR:g} ATR first within "
                   f"{horizon} bars{' (same session)' if same_session else ''}? Observed up % = up-first ÷ (up-first + down-first). "
                   "Hit % counts touches in the signal's own direction."),
        "note": (f"A calibrated engine shows observed ≈ stated. Buckets with fewer than {MIN_RESOLVED} resolved bars are noise; "
                 "the mean gap uses only buckets above that. Bars overlap, so neighbouring samples are not independent."),
    }


def _bucket_stats(name: str, group: list[dict]) -> dict:
    up = sum(r["outcome"] == "up" for r in group)
    down = sum(r["outcome"] == "down" for r in group)
    pointed = [r for r in group if r["direction"]]
    hits = sum(r["outcome"] == ("up" if r["direction"] > 0 else "down") for r in pointed)
    misses = sum(r["outcome"] == ("down" if r["direction"] > 0 else "up") for r in pointed)
    return {
        "bucket": name,
        "samples": len(group),
        "up_first": up,
        "down_first": down,
        "neither": sum(r["outcome"] == "neither" for r in group),
        "ambiguous": sum(r["outcome"] == "ambiguous" for r in group),
        "stated_bullish_pct": round(float(np.mean([r["bullish_pct"] for r in group])), 1) if group else None,
        "observed_up_pct": round(up / (up + down) * 100, 1) if up + down else None,
        "avg_forward_atr": round(float(np.mean([r["forward_atr"] for r in group])), 3) if group else None,
        "directional_samples": len(pointed),
        "hit_pct": round(hits / (hits + misses) * 100, 1) if hits + misses else None,
        "avg_forward_atr_in_direction": round(float(np.mean([r["direction"] * r["forward_atr"] for r in pointed])), 3) if pointed else None,
    }


def evaluate_signal_outcome(signal: dict, bars_after: pd.DataFrame, max_bars: int = 60, entry_window: int = 5) -> dict:
    """Track a recorded signal against the bars that followed it (strictly after its bar)."""
    direction = int(signal["direction"])
    if direction == 0 or signal.get("stop") is None:
        return {"status": "not_applicable"}
    entry_low, entry_high = float(signal["entry_low"]), float(signal["entry_high"])
    entry = (entry_low + entry_high) / 2
    stop, t1, t2 = float(signal["stop"]), float(signal["target1"]), float(signal["target2"])
    risk = abs(entry - stop)
    filled_at = None
    mfe = mae = 0.0
    hit_t1 = False
    for count, (ts, bar) in enumerate(bars_after.iterrows()):
        h, low, c = float(bar["high"]), float(bar["low"]), float(bar["close"])
        if filled_at is None:
            if low <= entry_high and h >= entry_low:
                filled_at = ts
            elif count + 1 >= entry_window:
                return {"status": "not_triggered", "checked_bars": count + 1}
            else:
                continue
        mfe = max(mfe, (h - entry) if direction > 0 else (entry - low))
        mae = max(mae, (entry - low) if direction > 0 else (h - entry))
        stop_hit = low <= stop if direction > 0 else h >= stop
        t1_hit = h >= t1 if direction > 0 else low <= t1
        t2_hit = h >= t2 if direction > 0 else low <= t2
        base = {"filled_at": filled_at.isoformat(), "exit_time": ts.isoformat(), "mfe_r": round(mfe / risk, 3), "mae_r": round(mae / risk, 3)}
        if stop_hit:
            status = "target1_then_stop" if hit_t1 else "stopped"
            return {**base, "status": status, "exit": stop, "r_multiple": round(direction * (stop - entry) / risk, 3)}
        if t2_hit:
            return {**base, "status": "target2", "exit": t2, "r_multiple": round(direction * (t2 - entry) / risk, 3)}
        hit_t1 = hit_t1 or t1_hit
        if count + 1 >= max_bars:
            return {**base, "status": "expired_after_target1" if hit_t1 else "expired", "exit": c,
                    "r_multiple": round(direction * (c - entry) / risk, 3)}
    if filled_at is None:
        return {"status": "open", "checked_bars": len(bars_after)}
    return {"status": "open", "filled_at": filled_at.isoformat(), "target1_hit": hit_t1, "mfe_r": round(mfe / risk, 3),
            "mae_r": round(mae / risk, 3), "checked_bars": len(bars_after)}
