import pandas as pd
import pytest
from helpers import make_ohlcv

from cc.analysis.backtest import BacktestParams, _check_exit, _try_fill, evaluate_signal_outcome, run_backtest
from cc.analysis.scanner import compute_stock_metrics, run_preset, score_stock
from cc.analysis.signal_engine import LABEL_BEAR, LABEL_BULL, LABEL_HIGH_RISK, LABEL_LOW_QUALITY
from cc.config import RuntimeSettings, SignalSettings
from cc.data.models import IST

ALL_SETUPS = [LABEL_BULL, LABEL_BEAR, LABEL_HIGH_RISK, LABEL_LOW_QUALITY]


def params(**overrides) -> BacktestParams:
    base = {"symbol": "TEST", "timeframe": "5m", "bars": 700, "warmup": 120, "window": 150, "labels": ALL_SETUPS}
    return BacktestParams(**(base | overrides))


def test_backtest_reports_and_enters_after_signal():
    frame = make_ohlcv(700, drift=0.0003, vol=0.0015, seed=21)
    result = run_backtest(frame, params(), RuntimeSettings(), intraday=True)
    summary = result["summary"]
    assert summary["period"]["bars"] == 700 and sum(summary["signal_label_counts"].values()) > 0
    assert summary["trades"] == len(result["trades"])
    for trade in result["trades"]:
        assert pd.Timestamp(trade["entry_time"]) > pd.Timestamp(trade["signal_time"])


def test_backtest_has_no_look_ahead():
    frame = make_ohlcv(700, drift=0.0003, vol=0.0015, seed=21)
    full = run_backtest(frame, params(), RuntimeSettings(), intraday=True)
    cut = run_backtest(frame.iloc[:500], params(), RuntimeSettings(), intraday=True)
    cutoff = frame.index[499]
    before_cut = [t for t in cut["trades"] if pd.Timestamp(t["exit_time"]) < cutoff]
    before_full = [t for t in full["trades"] if pd.Timestamp(t["exit_time"]) < cutoff]
    assert before_cut == before_full


def test_stop_is_assumed_first_on_ambiguous_bar():
    position = {"direction": 1, "entry": 100.0, "stop": 99.0, "target": 102.0, "entry_index": 0, "risk": 1.0, "mfe": 0.0, "mae": 0.0}
    ambiguous = pd.Series({"open": 100.5, "high": 102.5, "low": 98.5, "close": 101.0})
    assert _check_exit(position, ambiguous, 1, 10, BacktestParams(), False) == (99.0, "stop")
    gap = pd.Series({"open": 98.0, "high": 98.5, "low": 97.0, "close": 98.2})
    assert _check_exit(dict(position), gap, 2, 10, BacktestParams(), False) == (98.0, "stop (gap)")


def test_limit_entry_fills_at_zone_midpoint_or_better():
    ts = pd.Timestamp("2026-09-11 10:05", tz=IST)
    pending = {"direction": 1, "limit": 100.0, "stop": 98.0, "target": 104.0, "label": "BULLISH SETUP", "signal_time": ts,
               "expires": 5, "date": None, "confidence": 70.0, "bullish_pct": 70.0}
    untouched = pd.Series({"open": 101.0, "high": 102.0, "low": 100.5, "close": 101.5})
    assert _try_fill(pending, untouched, 1, ts, 0.0) == (None, False)
    touched, gapped = _try_fill(pending, pd.Series({"open": 101.0, "high": 101.2, "low": 99.5, "close": 100.2}), 1, ts, 0.0)
    assert not gapped and touched["entry"] == 100.0 and touched["risk"] == 2.0
    better, _ = _try_fill(pending, pd.Series({"open": 99.0, "high": 99.8, "low": 98.5, "close": 99.5}), 1, ts, 0.0)
    assert better["entry"] == 99.0 and better["risk"] == 2.0  # R stays measured against the planned risk
    assert _try_fill(pending, pd.Series({"open": 97.5, "high": 98.0, "low": 97.0, "close": 97.8}), 1, ts, 0.0) == (None, True)
    short = {**pending, "direction": -1, "limit": 100.0, "stop": 102.0, "target": 96.0}
    filled, _ = _try_fill(short, pd.Series({"open": 99.0, "high": 100.4, "low": 98.8, "close": 100.1}), 1, ts, 0.0002)
    assert filled["entry"] == pytest.approx(100.0 * (1 - 0.0002))


def _bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    index = pd.date_range("2026-09-11 09:20", periods=len(rows), freq="5min", tz=IST)
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)


def test_signal_outcome_tracking():
    signal = {"direction": 1, "entry_low": 99.5, "entry_high": 100.5, "stop": 98.0, "target1": 102.0, "target2": 104.0}
    hit = evaluate_signal_outcome(signal, _bars([(100, 100.6, 99.8, 100.2), (101, 102.5, 100.5, 102.2), (103, 104.2, 102.5, 104.0)]))
    assert hit["status"] == "target2" and hit["r_multiple"] == pytest.approx(2.0)
    stopped = evaluate_signal_outcome(signal, _bars([(100, 100.4, 99.9, 100.1), (99.5, 99.6, 97.5, 97.8)]))
    assert stopped["status"] == "stopped" and stopped["r_multiple"] == pytest.approx(-1.0)
    missed = evaluate_signal_outcome(signal, _bars([(103, 104, 102, 103.5)] * 5))
    assert missed["status"] == "not_triggered"
    assert evaluate_signal_outcome(signal, _bars([(100, 100.4, 99.9, 100.1)]))["status"] == "open"


def test_stock_metrics_scores_and_presets():
    daily = make_ohlcv(300, freq="1D", drift=0.002, vol=0.01, seed=31, base=1000)
    bench = make_ohlcv(300, freq="1D", drift=0.0, vol=0.008, seed=32)["close"]
    metrics = compute_stock_metrics(daily, bench, SignalSettings())
    assert not metrics["insufficient"] and metrics["rs_60"] is not None and metrics["avg_traded_value_cr"] is not None
    fundamentals = {"returnOnEquity": 0.2, "debtToEquity": 50, "revenueGrowth": 0.12, "earningsGrowth": 0.1,
                    "profitMargins": 0.15, "trailingPE": 25}
    score = score_stock(metrics, fundamentals)
    assert 0 <= score["total"] <= 100
    assert next(c for c in score["components"] if c["name"] == "fundamentals")["score"] == 100
    no_fundamentals = score_stock(metrics, None)
    assert "fundamentals" in no_fundamentals["missing"] and no_fundamentals["coverage"] < 1
    assert isinstance(run_preset({"X": metrics}, "near_52w_high"), list)
    with pytest.raises(ValueError):
        run_preset({"X": metrics}, "not_a_preset")


def test_insufficient_daily_history():
    metrics = compute_stock_metrics(make_ohlcv(30, freq="1D"), None, SignalSettings())
    assert metrics["insufficient"] is True
    assert score_stock(metrics)["rating"] == "Insufficient data"
