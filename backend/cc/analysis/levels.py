"""Support/resistance engine: session levels, confirmed swings, VWAP, moving averages,
volume nodes, option-OI walls, breakout levels and simple trendlines."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Level:
    price: float
    kind: str  # support | resistance
    label: str
    source: str
    strength: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LevelSet:
    price: float
    atr: float | None
    levels: list[Level]
    nearest_support: Level | None
    nearest_resistance: Level | None
    breakout_level: float | None
    breakdown_level: float | None
    trendlines: list[dict] = field(default_factory=list)
    session: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "price": self.price,
            "atr": self.atr,
            "levels": [lvl.to_dict() for lvl in self.levels],
            "nearest_support": self.nearest_support.to_dict() if self.nearest_support else None,
            "nearest_resistance": self.nearest_resistance.to_dict() if self.nearest_resistance else None,
            "breakout_level": self.breakout_level,
            "breakdown_level": self.breakdown_level,
            "trendlines": self.trendlines,
            "session": self.session,
        }


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def swing_points(df: pd.DataFrame, lookback: int) -> tuple[pd.Series, pd.Series]:
    """Confirmed swing highs/lows: a bar is a pivot once ``lookback`` later bars exist (no look-ahead)."""
    window = 2 * lookback + 1
    highs = df["high"].where(df["high"] == df["high"].rolling(window, center=True).max())
    lows = df["low"].where(df["low"] == df["low"].rolling(window, center=True).min())
    return highs.dropna(), lows.dropna()


def session_levels(df: pd.DataFrame, intraday: bool) -> dict:
    if df.empty:
        return {}
    if intraday:
        dates = pd.Index(df.index.date)
        last_day = dates[-1]
        today = df[dates == last_day]
        previous_days = sorted({d for d in dates if d < last_day})
        out = {"day_high": float(today["high"].max()), "day_low": float(today["low"].min()), "day_open": float(today["open"].iloc[0])}
        if previous_days:
            prev = df[dates == previous_days[-1]]
            out.update({"prev_high": float(prev["high"].max()), "prev_low": float(prev["low"].min()), "prev_close": float(prev["close"].iloc[-1])})
        return out
    if len(df) >= 2:
        prev = df.iloc[-2]
        return {"prev_high": float(prev["high"]), "prev_low": float(prev["low"]), "prev_close": float(prev["close"])}
    return {}


def volume_nodes(df: pd.DataFrame, bins: int = 24, top: int = 3) -> list[float]:
    recent = df.tail(400)
    if recent["volume"].isna().mean() > 0.1 or recent["volume"].sum() <= 0:
        return []
    low, high = recent["low"].min(), recent["high"].max()
    if not np.isfinite(low) or high <= low:
        return []
    typical = (recent["high"] + recent["low"] + recent["close"]) / 3
    hist, edges = np.histogram(typical, bins=bins, range=(low, high), weights=recent["volume"])
    centers = (edges[:-1] + edges[1:]) / 2
    order = np.argsort(hist)[::-1][:top]
    return [float(centers[i]) for i in order if hist[i] > 0]


def compute_levels(ind: pd.DataFrame, intraday: bool, swing_lookback: int = 3, breakout_lookback: int = 20,
                   option_walls: dict | None = None) -> LevelSet:
    last = ind.iloc[-1]
    price = float(last["close"])
    atr = _finite(last.get("atr"))
    tolerance = 0.15 * atr if atr else price * 0.0005
    candidates: list[tuple[float, str, str, int]] = []

    session = session_levels(ind, intraday)
    labels = {
        "prev_high": ("Previous day high", 3), "prev_low": ("Previous day low", 3), "prev_close": ("Previous close", 2),
        "day_high": ("Day high", 2), "day_low": ("Day low", 2),
    }
    for key, (label, strength) in labels.items():
        if key in session:
            candidates.append((session[key], label, "session OHLC", strength))

    highs, lows = swing_points(ind, swing_lookback)
    for ts, value in highs.tail(5).items():
        candidates.append((float(value), f"Swing high {ts:%d %b %H:%M}" if intraday else f"Swing high {ts:%d %b %Y}", "confirmed swing", 2))
    for ts, value in lows.tail(5).items():
        candidates.append((float(value), f"Swing low {ts:%d %b %H:%M}" if intraday else f"Swing low {ts:%d %b %Y}", "confirmed swing", 2))

    for column, label, strength in (("vwap", "VWAP", 2), ("ema_slow", "EMA slow", 1), ("sma50", "SMA 50", 2), ("sma200", "SMA 200", 3)):
        value = _finite(last.get(column))
        if value:
            candidates.append((value, label, "internal indicator", strength))

    if ind.attrs.get("has_volume"):
        for node in volume_nodes(ind):
            candidates.append((node, "High-volume node", "volume profile", 1))

    if option_walls:
        if option_walls.get("call_wall"):
            candidates.append((float(option_walls["call_wall"]), f"Highest call OI {option_walls['call_wall']:g}", "option chain OI", 3))
        if option_walls.get("put_wall"):
            candidates.append((float(option_walls["put_wall"]), f"Highest put OI {option_walls['put_wall']:g}", "option chain OI", 3))

    levels = _cluster(sorted(candidates), tolerance, price)
    supports = [lvl for lvl in levels if lvl.price < price - 0.02 * (atr or 0)]
    resistances = [lvl for lvl in levels if lvl.price > price + 0.02 * (atr or 0)]

    prior = ind.iloc[-(breakout_lookback + 1):-1]
    breakout = float(prior["high"].max()) if len(prior) >= breakout_lookback // 2 else None
    breakdown = float(prior["low"].min()) if len(prior) >= breakout_lookback // 2 else None

    return LevelSet(
        price=price,
        atr=atr,
        levels=levels,
        nearest_support=max(supports, key=lambda lvl: lvl.price) if supports else None,
        nearest_resistance=min(resistances, key=lambda lvl: lvl.price) if resistances else None,
        breakout_level=breakout,
        breakdown_level=breakdown,
        trendlines=_trendlines(ind, highs, lows),
        session=session,
    )


def _cluster(candidates: list[tuple[float, str, str, int]], tolerance: float, price: float) -> list[Level]:
    clusters: list[list[tuple[float, str, str, int]]] = []
    for item in candidates:
        if clusters and abs(item[0] - clusters[-1][-1][0]) <= tolerance:
            clusters[-1].append(item)
        else:
            clusters.append([item])
    levels = []
    for group in clusters:
        strongest = max(group, key=lambda g: g[3])
        value = round(sum(g[0] for g in group) / len(group), 2)
        labels = list(dict.fromkeys(g[1] for g in group))
        sources = list(dict.fromkeys(g[2] for g in group))
        levels.append(Level(
            price=value, kind="support" if value < price else "resistance", label=" + ".join(labels),
            source=", ".join(sources), strength=min(3, strongest[3] + (1 if len(group) > 1 else 0)),
        ))
    return levels


def _trendlines(ind: pd.DataFrame, highs: pd.Series, lows: pd.Series) -> list[dict]:
    lines = []
    positions = {ts: i for i, ts in enumerate(ind.index)}
    last_pos = len(ind) - 1
    if len(lows) >= 2:
        (t1, p1), (t2, p2) = list(lows.tail(2).items())
        if p2 > p1:
            slope = (p2 - p1) / (positions[t2] - positions[t1])
            lines.append({"kind": "rising support", "points": [[t1.isoformat(), float(p1)], [t2.isoformat(), float(p2)]],
                          "projection": round(float(p2 + slope * (last_pos - positions[t2])), 2)})
    if len(highs) >= 2:
        (t1, p1), (t2, p2) = list(highs.tail(2).items())
        if p2 < p1:
            slope = (p2 - p1) / (positions[t2] - positions[t1])
            lines.append({"kind": "falling resistance", "points": [[t1.isoformat(), float(p1)], [t2.isoformat(), float(p2)]],
                          "projection": round(float(p2 + slope * (last_pos - positions[t2])), 2)})
    return lines
