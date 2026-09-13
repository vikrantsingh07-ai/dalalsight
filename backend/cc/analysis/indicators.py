"""Causal technical indicators on OHLCV frames (every value uses only current and past bars)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import SignalSettings


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def _wilder(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = _wilder(delta.clip(lower=0), period)
    loss = _wilder(-delta.clip(upper=0), period)
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    out = out.where(loss != 0, 100.0)
    return out.where(gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    signal_line = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": signal_line, "macd_hist": line - signal_line})


def bollinger(close: pd.Series, period: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, period)
    std = close.rolling(period, min_periods=period).std(ddof=0)
    upper, lower = mid + k * std, mid - k * std
    return pd.DataFrame({"bb_mid": mid, "bb_upper": upper, "bb_lower": lower, "bb_width": (upper - lower) / mid})


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return _wilder(true_range(df), period)


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr_ = atr(df, period)
    plus_di = 100 * _wilder(plus_dm, period) / atr_
    minus_di = 100 * _wilder(minus_dm, period) / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return pd.DataFrame({"adx": _wilder(dx, period), "plus_di": plus_di, "minus_di": minus_di})


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    atr_ = atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2
    upper_basic = (hl2 + multiplier * atr_).to_numpy()
    lower_basic = (hl2 - multiplier * atr_).to_numpy()
    close = df["close"].to_numpy()
    n = len(df)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    line = np.full(n, np.nan)
    direction = np.zeros(n)
    for i in range(n):
        if np.isnan(upper_basic[i]):
            continue
        if i == 0 or np.isnan(upper[i - 1]):
            upper[i], lower[i] = upper_basic[i], lower_basic[i]
            direction[i] = 1 if close[i] >= hl2.iloc[i] else -1
        else:
            upper[i] = upper_basic[i] if upper_basic[i] < upper[i - 1] or close[i - 1] > upper[i - 1] else upper[i - 1]
            lower[i] = lower_basic[i] if lower_basic[i] > lower[i - 1] or close[i - 1] < lower[i - 1] else lower[i - 1]
            if direction[i - 1] == -1 and close[i] > upper[i - 1]:
                direction[i] = 1
            elif direction[i - 1] == 1 and close[i] < lower[i - 1]:
                direction[i] = -1
            else:
                direction[i] = direction[i - 1]
        line[i] = lower[i] if direction[i] == 1 else upper[i]
    return pd.DataFrame({"supertrend": line, "supertrend_dir": direction}, index=df.index)


def has_real_volume(df: pd.DataFrame) -> bool:
    if "volume" not in df or df.attrs.get("has_volume") is False:
        return False
    volume = df["volume"]
    return bool(len(volume) and volume.notna().mean() > 0.9 and (volume.fillna(0) > 0).mean() > 0.8)


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """Volume-weighted average price anchored to each trading session. NaN without real volume."""
    if not has_real_volume(df):
        return pd.Series(np.nan, index=df.index)
    typical = (df["high"] + df["low"] + df["close"]) / 3
    sessions = df.index.date
    pv = (typical * df["volume"]).groupby(sessions).cumsum()
    vol = df["volume"].groupby(sessions).cumsum()
    return pv / vol.replace(0, np.nan)


def compute_indicators(df: pd.DataFrame, cfg: SignalSettings, intraday: bool = True) -> pd.DataFrame:
    """Return ``df`` plus indicator columns. Requires lowercase OHLCV columns."""
    out = df.copy()
    close = out["close"]
    out["ema_fast"] = ema(close, cfg.ema_fast)
    out["ema_slow"] = ema(close, cfg.ema_slow)
    out["ema20"] = ema(close, 20)
    out["ema50"] = ema(close, 50)
    out["sma50"] = sma(close, 50)
    out["sma200"] = sma(close, 200)
    out["rsi"] = rsi(close, cfg.rsi_period)
    out = out.join(macd(close))
    out = out.join(bollinger(close))
    out["atr"] = atr(out, cfg.atr_period)
    out["atr_pct"] = out["atr"] / close * 100
    out["atr_sma"] = sma(out["atr"], 20)
    out = out.join(supertrend(out, cfg.supertrend_period, cfg.supertrend_mult))
    out = out.join(adx(out))
    volume_ok = has_real_volume(df)
    out["vol_sma"] = sma(out["volume"], 20) if volume_ok else np.nan
    out["vwap"] = session_vwap(df) if (intraday and volume_ok) else np.nan
    out.attrs = dict(df.attrs)
    out.attrs["has_volume"] = volume_ok
    return out
