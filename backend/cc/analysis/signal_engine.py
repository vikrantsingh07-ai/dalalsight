"""Signal confidence engine.

Transparent weighted scoring — no random numbers, no single-indicator signals:

* each component returns a directional score in [-1, +1], an availability flag and evidence
* composite S = Σ wᵢ·sᵢ / Σ wᵢ over available components
* bullish scenario = 50 + 50·S (model-estimated, based on current signals); bearish = 100 − bullish
* model confidence = (weight of available components agreeing with the direction ÷ available
  weight) × coverage, where coverage = available weight ÷ total weight
* trade plans are derived from ATR and detected levels; every value states its basis
* insufficient evidence → "NO TRADE / WAIT FOR CONFIRMATION"
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from ..config import RiskSettings, SignalSettings
from .events import TechEvent
from .levels import LevelSet, swing_points
from .regime import Regime

LABEL_BULL = "BULLISH SETUP"
LABEL_BEAR = "BEARISH SETUP"
LABEL_WATCH = "WATCH"
LABEL_NO_TRADE = "NO TRADE / WAIT FOR CONFIRMATION"
LABEL_HIGH_RISK = "HIGH-RISK SETUP"
LABEL_LOW_QUALITY = "LOW-QUALITY SETUP"
DISCLAIMER = (
    "Model-estimated probabilities from current technical signals, not guaranteed outcomes and not "
    "investment advice. Verify levels on your broker terminal before acting."
)


@dataclass
class Component:
    name: str
    weight: float
    available: bool
    score: float = 0.0
    evidence: list[str] = field(default_factory=list)
    unavailable_reason: str | None = None

    @property
    def contribution(self) -> float:
        return self.weight * self.score if self.available else 0.0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["contribution"] = round(self.contribution, 3)
        data["score"] = round(self.score, 3)
        return data


@dataclass
class TradePlan:
    direction: int
    entry_low: float
    entry_high: float
    stop: float
    stop_basis: str
    target1: float
    target1_basis: str
    target2: float
    target2_basis: str
    risk_per_unit: float
    risk_reward: float
    invalidation: str
    position_size_units: float | None = None
    position_size_basis: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SignalResult:
    symbol: str
    timeframe: str
    bar_time: str
    price: float
    label: str
    direction: int
    bullish_pct: float
    bearish_pct: float
    model_confidence: float
    coverage: float
    agreement: float
    composite: float
    components: list[Component]
    plan: TradePlan | None
    reasons: list[str]
    risks: list[str]
    regime: str
    data_sources: list[str]
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bar_time": self.bar_time,
            "price": self.price,
            "label": self.label,
            "direction": self.direction,
            "bullish_pct": self.bullish_pct,
            "bearish_pct": self.bearish_pct,
            "model_confidence": self.model_confidence,
            "coverage": self.coverage,
            "agreement": self.agreement,
            "composite": self.composite,
            "components": [c.to_dict() for c in self.components],
            "plan": self.plan.to_dict() if self.plan else None,
            "reasons": self.reasons,
            "risks": self.risks,
            "regime": self.regime,
            "data_sources": self.data_sources,
            "disclaimer": self.disclaimer,
            "method": "weighted component scoring; confidence = agreeing weight share × coverage",
        }


def _f(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _clip(value: float) -> float:
    return float(max(-1.0, min(1.0, value)))


def _events(events: list[TechEvent], *keys: str) -> list[TechEvent]:
    return [e for e in events if e.key in keys]


def score_components(ind: pd.DataFrame, events: list[TechEvent], levels: LevelSet, regime: Regime,
                     options: dict | None, cfg: SignalSettings) -> list[Component]:
    w = cfg.weights
    last, prev = ind.iloc[-1], ind.iloc[-2]
    close = float(last["close"])
    atr = _f(last.get("atr"))
    has_volume = bool(ind.attrs.get("has_volume"))
    comps: list[Component] = []

    # Trend
    trend_scores = {"STRONG_BULLISH_TREND": 1.0, "WEAK_BULLISH_TREND": 0.6, "STRONG_BEARISH_TREND": -1.0,
                    "WEAK_BEARISH_TREND": -0.6, "RANGE_BOUND": 0.0}
    if regime.code == "INSUFFICIENT_DATA":
        comps.append(Component("trend", w.trend, False, unavailable_reason="not enough bars for trend regime"))
    else:
        ema50 = _f(last.get("ema50"))
        base = trend_scores.get(regime.code)
        if base is None:
            base = 0.8 * regime.direction if regime.code == "BREAKOUT" else (0.2 if ema50 and close > ema50 else -0.2)
        evidence = [f"regime: {regime.label}"]
        sma200 = _f(last.get("sma200"))
        if sma200:
            base += 0.2 if close > sma200 else -0.2
            evidence.append(f"price {'above' if close > sma200 else 'below'} SMA 200 ({sma200:,.2f})")
        comps.append(Component("trend", w.trend, True, _clip(base), evidence))

    # Momentum
    rsi, hist = _f(last.get("rsi")), ind["macd_hist"].dropna()
    if rsi is None or len(hist) < 4:
        comps.append(Component("momentum", w.momentum, False, unavailable_reason="RSI/MACD warming up"))
    else:
        h = hist.iloc[-3:].to_numpy()
        score = _clip((rsi - 50) / 20) * 0.5
        expanding = abs(h[-1]) > abs(h[-2])
        score += float(np.sign(h[-1])) * (0.3 if expanding else 0.15)
        rsi_prev = _f(ind["rsi"].iloc[-4])
        evidence = [f"RSI {rsi:.1f}", f"MACD histogram {h[-1]:+.2f} ({'expanding' if expanding else 'contracting'})"]
        if rsi_prev is not None and abs(rsi - rsi_prev) > 3:
            score += 0.2 * float(np.sign(rsi - rsi_prev))
            evidence.append(f"RSI {'rising' if rsi > rsi_prev else 'falling'} ({rsi - rsi_prev:+.1f} over 3 bars)")
        if rsi >= cfg.rsi_overbought or rsi <= cfg.rsi_oversold:
            evidence.append("RSI at an extreme: continuation and reversal both possible")
        comps.append(Component("momentum", w.momentum, True, _clip(score), evidence))

    # Volume
    vol_avg, volume = _f(prev.get("vol_sma")), _f(last.get("volume"))
    if not has_volume or not vol_avg or volume is None:
        comps.append(Component("volume", w.volume, False,
                               unavailable_reason="no real volume from the provider (spot indices carry none; a futures feed is required)"))
    else:
        ratio = volume / vol_avg
        bar_dir = 1.0 if close >= float(last["open"]) else -1.0
        score = bar_dir * min(1.0, 0.4 + (ratio - 1) / 1.5) if ratio >= cfg.volume_confirm_mult else 0.0
        recent = ind.tail(10)
        signed = (np.sign(recent["close"] - recent["open"]) * recent["volume"]).sum() / max(recent["volume"].sum(), 1)
        score += 0.3 * float(signed)
        comps.append(Component("volume", w.volume, True, _clip(score),
                               [f"last bar volume {ratio:.2f}× 20-bar average", f"10-bar signed volume balance {signed:+.2f}"]))

    # EMA structure
    fast, slow = _f(last.get("ema_fast")), _f(last.get("ema_slow"))
    if fast is None or slow is None:
        comps.append(Component("ema_structure", w.ema_structure, False, unavailable_reason="EMAs warming up"))
    else:
        score = 0.5 if fast > slow else -0.5
        evidence = [f"EMA {cfg.ema_fast} {fast:,.2f} {'above' if fast > slow else 'below'} EMA {cfg.ema_slow} {slow:,.2f}"]
        confirmed = _events(events, "ema_cross_bull_confirmed", "ema_cross_bear_confirmed")
        crossed = _events(events, "ema_cross_bull", "ema_cross_bear")
        if confirmed:
            score += 0.3 * confirmed[0].direction
            evidence.append(confirmed[0].message)
        elif crossed:
            score += 0.15 * crossed[0].direction
            evidence.append(crossed[0].message + " (awaiting confirmation)")
        prior = _f(ind["ema_fast"].iloc[-4])
        if prior:
            slope = (fast - prior) / prior * 100
            score += 0.2 * float(np.sign(slope)) if abs(slope) > 0.01 else 0.0
            evidence.append(f"EMA {cfg.ema_fast} slope {slope:+.3f}% over 3 bars")
        if atr:
            stretch = (close - slow) / atr
            evidence.append(f"price {stretch:+.2f} ATR from EMA {cfg.ema_slow}")
            if abs(stretch) > 2.5:
                score -= 0.3 * float(np.sign(stretch))
                evidence.append("price extended from EMA: pullback risk")
        comps.append(Component("ema_structure", w.ema_structure, True, _clip(score), evidence))

    # VWAP
    vwap = _f(last.get("vwap"))
    if not vwap:
        comps.append(Component("vwap", w.vwap, False, unavailable_reason="VWAP needs real intraday volume (not available for this instrument/provider)"))
    else:
        score = 0.6 if close > vwap else -0.6
        evidence = [f"price {'above' if close > vwap else 'below'} VWAP {vwap:,.2f}"]
        for event in _events(events, "vwap_breakout", "vwap_breakdown", "vwap_rejection_bull", "vwap_rejection_bear"):
            score += 0.4 * event.direction
            evidence.append(event.message)
        comps.append(Component("vwap", w.vwap, True, _clip(score), evidence))

    # Market structure
    highs, lows = swing_points(ind.tail(150), cfg.swing_lookback)
    if len(highs) < 2 or len(lows) < 2:
        comps.append(Component("market_structure", w.market_structure, False, unavailable_reason="not enough confirmed swings"))
    else:
        h1, h2 = highs.iloc[-2], highs.iloc[-1]
        l1, l2 = lows.iloc[-2], lows.iloc[-1]
        if h2 > h1 and l2 > l1:
            score, desc = 0.7, "higher highs and higher lows"
        elif h2 < h1 and l2 < l1:
            score, desc = -0.7, "lower highs and lower lows"
        else:
            score, desc = 0.0, "mixed swing structure"
        evidence = [f"{desc} (swing highs {h1:,.2f}→{h2:,.2f}, lows {l1:,.2f}→{l2:,.2f})"]
        for event in _events(events, "breakout", "breakdown", "false_breakout", "false_breakdown"):
            score += (0.3 if event.kind in ("breakout", "breakdown") else 0.4) * event.direction
            evidence.append(event.message)
        if atr and levels.nearest_resistance and levels.nearest_resistance.price - close < 0.5 * atr:
            score -= 0.2
            evidence.append(f"resistance {levels.nearest_resistance.price:,.2f} within 0.5 ATR")
        if atr and levels.nearest_support and close - levels.nearest_support.price < 0.5 * atr:
            score += 0.2
            evidence.append(f"support {levels.nearest_support.price:,.2f} within 0.5 ATR")
        comps.append(Component("market_structure", w.market_structure, True, _clip(score), evidence))

    # Volatility (confirms the direction of the latest move when expanding)
    atr_sma = _f(last.get("atr_sma"))
    if not atr or not atr_sma or len(ind) < 5:
        comps.append(Component("volatility", w.volatility, False, unavailable_reason="ATR warming up"))
    else:
        ratio = atr / atr_sma
        move = close - float(ind["close"].iloc[-4])
        score = 0.5 * float(np.sign(move)) if ratio > 1.2 else 0.0
        comps.append(Component("volatility", w.volatility, True, score,
                               [f"ATR {ratio:.2f}× average ({'expanding' if ratio > 1.2 else 'contracting' if ratio < 0.8 else 'normal'})"]))

    # Options positioning
    if not options:
        comps.append(Component("options", w.options, False, unavailable_reason="no option chain for this instrument, or chain not loaded"))
    else:
        score, evidence = 0.0, []
        pcr = _f(options.get("pcr_oi"))
        if pcr is not None:
            score += 0.4 if pcr > 1.2 else -0.4 if pcr < 0.8 else 0.0
            evidence.append(f"PCR (OI) {pcr:.2f}")
        call_chg, put_chg = _f(options.get("call_oi_change")), _f(options.get("put_oi_change"))
        if call_chg is not None and put_chg is not None and (abs(call_chg) + abs(put_chg)) > 0:
            if put_chg > call_chg:
                score += 0.3
                evidence.append("put OI added faster than call OI (put writing support)")
            elif call_chg > put_chg:
                score -= 0.3
                evidence.append("call OI added faster than put OI (call writing resistance)")
        call_wall = _f(options.get("call_wall"))
        if call_wall and atr and 0 < call_wall - close < 0.5 * atr:
            score -= 0.2
            evidence.append(f"spot within 0.5 ATR of the highest call OI strike {call_wall:g}")
        comps.append(Component("options", w.options, bool(evidence), _clip(score), evidence,
                               None if evidence else "option metrics missing"))
    return comps


def build_signal(symbol: str, timeframe: str, ind: pd.DataFrame, events: list[TechEvent], levels: LevelSet,
                 regime: Regime, options: dict | None, cfg: SignalSettings, risk: RiskSettings,
                 data_sources: list[str]) -> SignalResult:
    components = score_components(ind, events, levels, regime, options, cfg)
    total = sum(c.weight for c in components)
    available = [c for c in components if c.available and c.weight > 0]
    avail_weight = sum(c.weight for c in available)
    coverage = avail_weight / total if total else 0.0
    composite = sum(c.contribution for c in available) / avail_weight if avail_weight else 0.0
    direction = int(np.sign(composite)) if abs(composite) >= 0.05 else 0
    agreeing = sum(c.weight for c in available if direction and np.sign(c.score) == direction and abs(c.score) >= 0.15)
    agreement = agreeing / avail_weight if avail_weight else 0.0
    bullish = round(50 + 50 * composite, 1)
    confidence = round(100 * agreement * coverage, 1)
    last = ind.iloc[-1]
    price = float(last["close"])
    atr = _f(last.get("atr"))

    reasons = [f"{c.name}: {e}" for c in sorted(available, key=lambda c: -abs(c.contribution)) for e in c.evidence[:2]
               if direction and np.sign(c.score) == direction]
    risks = [f"{c.name}: {e}" for c in available for e in c.evidence[:1] if direction and np.sign(c.score) == -direction]
    risks += [f"{c.name} unavailable: {c.unavailable_reason}" for c in components if not c.available]

    label, plan = LABEL_NO_TRADE, None
    if coverage < cfg.min_coverage:
        reasons.insert(0, f"data coverage {coverage:.0%} below the {cfg.min_coverage:.0%} minimum")
    elif direction and confidence >= cfg.min_confidence and (bullish >= cfg.bullish_threshold or bullish <= cfg.bearish_threshold):
        plan = build_plan(direction, ind, levels, atr, cfg, risk)
        if plan is None:
            reasons.insert(0, "no valid stop within the allowed ATR distance")
        else:
            label = LABEL_BULL if direction > 0 else LABEL_BEAR
            opposing = levels.nearest_resistance if direction > 0 else levels.nearest_support
            if plan.risk_reward < cfg.min_risk_reward:
                label = LABEL_LOW_QUALITY
                risks.insert(0, f"risk/reward 1:{plan.risk_reward:.2f} below the 1:{cfg.min_risk_reward:.2f} minimum")
            elif regime.code == "HIGH_VOLATILITY" or _events(events, "false_breakout", "false_breakdown"):
                label = LABEL_HIGH_RISK
                risks.insert(0, "high volatility or possible false breakout")
            elif atr and opposing and abs(opposing.price - price) < 0.5 * atr:
                label = LABEL_HIGH_RISK
                risks.insert(0, f"opposing level {opposing.price:,.2f} within 0.5 ATR")
    elif abs(bullish - 50) >= cfg.watch_band:
        label = LABEL_WATCH
    return SignalResult(
        symbol=symbol, timeframe=timeframe, bar_time=ind.index[-1].isoformat(), price=price, label=label,
        direction=direction if label != LABEL_NO_TRADE else 0, bullish_pct=bullish, bearish_pct=round(100 - bullish, 1),
        model_confidence=confidence, coverage=round(coverage, 3), agreement=round(agreement, 3),
        composite=round(composite, 4), components=components, plan=plan, reasons=reasons[:8], risks=risks[:8],
        regime=regime.label, data_sources=data_sources,
    )


def _round_tick(value: float, tick: float = 0.05) -> float:
    return round(round(value / tick) * tick, 2)


def build_plan(direction: int, ind: pd.DataFrame, levels: LevelSet, atr: float | None, cfg: SignalSettings,
               risk: RiskSettings) -> TradePlan | None:
    if not atr:
        return None
    last = ind.iloc[-1]
    price = float(last["close"])
    highs, lows = swing_points(ind.tail(150), cfg.swing_lookback)
    vwap, ema_slow = _f(last.get("vwap")), _f(last.get("ema_slow"))
    buffer = 0.2 * atr
    if direction > 0:
        entry_low, entry_high = price - 0.3 * atr, price
        mid = (entry_low + entry_high) / 2
        candidates = []
        if len(lows):
            candidates.append((float(lows.iloc[-1]) - buffer, f"below last swing low {float(lows.iloc[-1]):,.2f}"))
        if ema_slow and ema_slow < entry_low:
            candidates.append((ema_slow - buffer, f"below EMA {cfg.ema_slow} {ema_slow:,.2f}"))
        if vwap and vwap < entry_low:
            candidates.append((vwap - buffer, f"below VWAP {vwap:,.2f}"))
        if levels.nearest_support:
            candidates.append((levels.nearest_support.price - buffer, f"below support {levels.nearest_support.price:,.2f} ({levels.nearest_support.label})"))
        valid = [c for c in candidates if c[0] <= entry_low - 0.5 * atr and mid - c[0] <= risk.max_stop_atr * atr]
        stop, stop_basis = max(valid, key=lambda c: c[0]) if valid else (entry_low - atr, "1.0 ATR below the entry zone (no structural level in range)")
        risk_unit = mid - stop
        above = sorted([lvl for lvl in levels.levels if lvl.price > entry_high], key=lambda lvl: lvl.price)
        t1, t1_basis = (above[0].price, f"nearest resistance ({above[0].label})") if above else (mid + 2 * risk_unit, "2R projection (no resistance level above)")
        t2, t2_basis = (above[1].price, f"next resistance ({above[1].label})") if len(above) > 1 else (t1 + risk_unit, "T1 + 1R projection")
        rr = (t1 - mid) / risk_unit if risk_unit > 0 else 0.0
        invalidation = f"close below {stop:,.2f} ({stop_basis})" + (f" or sustained trade below VWAP {vwap:,.2f}" if vwap else "")
    else:
        entry_low, entry_high = price, price + 0.3 * atr
        mid = (entry_low + entry_high) / 2
        candidates = []
        if len(highs):
            candidates.append((float(highs.iloc[-1]) + buffer, f"above last swing high {float(highs.iloc[-1]):,.2f}"))
        if ema_slow and ema_slow > entry_high:
            candidates.append((ema_slow + buffer, f"above EMA {cfg.ema_slow} {ema_slow:,.2f}"))
        if vwap and vwap > entry_high:
            candidates.append((vwap + buffer, f"above VWAP {vwap:,.2f}"))
        if levels.nearest_resistance:
            candidates.append((levels.nearest_resistance.price + buffer, f"above resistance {levels.nearest_resistance.price:,.2f} ({levels.nearest_resistance.label})"))
        valid = [c for c in candidates if c[0] >= entry_high + 0.5 * atr and c[0] - mid <= risk.max_stop_atr * atr]
        stop, stop_basis = min(valid, key=lambda c: c[0]) if valid else (entry_high + atr, "1.0 ATR above the entry zone (no structural level in range)")
        risk_unit = stop - mid
        below = sorted([lvl for lvl in levels.levels if lvl.price < entry_low], key=lambda lvl: -lvl.price)
        t1, t1_basis = (below[0].price, f"nearest support ({below[0].label})") if below else (mid - 2 * risk_unit, "2R projection (no support level below)")
        t2, t2_basis = (below[1].price, f"next support ({below[1].label})") if len(below) > 1 else (t1 - risk_unit, "T1 − 1R projection")
        rr = (mid - t1) / risk_unit if risk_unit > 0 else 0.0
        invalidation = f"close above {stop:,.2f} ({stop_basis})" + (f" or sustained trade above VWAP {vwap:,.2f}" if vwap else "")
    if risk_unit <= 0 or risk_unit > risk.max_stop_atr * atr:
        return None
    capital_at_risk = risk.capital * risk.risk_per_trade_pct / 100
    return TradePlan(
        direction=direction, entry_low=_round_tick(entry_low), entry_high=_round_tick(entry_high),
        stop=_round_tick(stop), stop_basis=stop_basis, target1=_round_tick(t1), target1_basis=t1_basis,
        target2=_round_tick(t2), target2_basis=t2_basis, risk_per_unit=round(risk_unit, 2), risk_reward=round(rr, 2),
        invalidation=invalidation, position_size_units=round(capital_at_risk / risk_unit, 2),
        position_size_basis=f"{risk.risk_per_trade_pct}% of ₹{risk.capital:,.0f} capital at risk ÷ risk per unit (before lot-size rounding)",
    )
