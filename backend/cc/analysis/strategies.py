"""Options strategy builder, evaluator and suggester.

* legs are priced from the live chain (bid/ask mid, else last traded price); a missing quote stops the build
* payoff at expiry and a T+0 theoretical curve (Black-Scholes with each leg's IV)
* breakevens, max profit/loss (with unlimited detection), net premium and net Greeks
* probability of profit: lognormal terminal distribution with ATM IV — a model estimate
* SPAN/exposure margin needs a broker margin API and is reported as unavailable
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from math import erf, log, sqrt

import numpy as np
from tradingagents.dataflows.india.fno import bs_price, option_greeks

from ..data.models import DataUnavailable, OptionChain
from .options import leg_analytics, years_to_expiry


@dataclass
class Leg:
    option_type: str  # CE | PE
    side: int  # +1 buy, -1 sell
    strike: float
    lots: int
    premium: float
    iv: float | None  # decimal
    price_source: str = "mid"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["action"] = "BUY" if self.side > 0 else "SELL"
        return data


# (option type, side, strike offset in units of the width, extra steps)
TEMPLATES: dict[str, dict] = {
    "long_call": {"name": "Long call", "view": "bullish", "risk": "defined", "width": 0, "legs": [("CE", 1, 0, 0)]},
    "long_put": {"name": "Long put", "view": "bearish", "risk": "defined", "width": 0, "legs": [("PE", 1, 0, 0)]},
    "bull_call_spread": {"name": "Bull call spread", "view": "bullish", "risk": "defined", "width": 2,
                         "legs": [("CE", 1, 0, 0), ("CE", -1, 1, 0)]},
    "bear_put_spread": {"name": "Bear put spread", "view": "bearish", "risk": "defined", "width": 2,
                        "legs": [("PE", 1, 0, 0), ("PE", -1, -1, 0)]},
    "bull_put_spread": {"name": "Bull put spread (credit)", "view": "bullish", "risk": "defined", "width": 2,
                        "legs": [("PE", -1, 0, -1), ("PE", 1, -1, -1)]},
    "bear_call_spread": {"name": "Bear call spread (credit)", "view": "bearish", "risk": "defined", "width": 2,
                         "legs": [("CE", -1, 0, 1), ("CE", 1, 1, 1)]},
    "long_straddle": {"name": "Long straddle", "view": "big move", "risk": "defined", "width": 0,
                      "legs": [("CE", 1, 0, 0), ("PE", 1, 0, 0)]},
    "long_strangle": {"name": "Long strangle", "view": "big move", "risk": "defined", "width": 4,
                      "legs": [("CE", 1, 1, 0), ("PE", 1, -1, 0)]},
    "short_straddle": {"name": "Short straddle", "view": "range", "risk": "unlimited", "width": 0,
                       "legs": [("CE", -1, 0, 0), ("PE", -1, 0, 0)]},
    "short_strangle": {"name": "Short strangle", "view": "range", "risk": "unlimited", "width": 4,
                       "legs": [("CE", -1, 1, 0), ("PE", -1, -1, 0)]},
    "iron_condor": {"name": "Iron condor", "view": "range", "risk": "defined", "width": 4,
                    "legs": [("PE", 1, -2, 0), ("PE", -1, -1, 0), ("CE", -1, 1, 0), ("CE", 1, 2, 0)]},
    "iron_butterfly": {"name": "Iron butterfly", "view": "range", "risk": "defined", "width": 4,
                       "legs": [("PE", 1, -1, 0), ("PE", -1, 0, 0), ("CE", -1, 0, 0), ("CE", 1, 1, 0)]},
}


def _cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def build_template(key: str, chain: OptionChain, now: datetime, rate: float, lots: int = 1, width_steps: int | None = None) -> list[Leg]:
    if key not in TEMPLATES:
        raise ValueError(f"unknown strategy {key!r}")
    template = TEMPLATES[key]
    step, atm = chain.strike_step(), chain.atm_strike()
    if step is None or atm is None:
        raise DataUnavailable(f"{chain.symbol} strategy", "option chain has too few strikes", chain.provider)
    width = template["width"] if width_steps is None else width_steps
    if template["width"] and width < 1:
        raise ValueError("width_steps must be at least 1")
    years = years_to_expiry(chain.expiry, now)
    legs = []
    for option_type, side, width_units, extra_steps in template["legs"]:
        strike = atm + (width_units * width + extra_steps) * step
        legs.append(price_leg(chain, option_type, side, strike, lots, years, rate))
    return legs


def price_leg(chain: OptionChain, option_type: str, side: int, strike: float, lots: int, years: float, rate: float) -> Leg:
    row = chain.row(strike)
    leg = None if row is None else (row.ce if option_type == "CE" else row.pe)
    if leg is None:
        raise DataUnavailable(f"{chain.symbol} {strike:g} {option_type}", "strike not listed in the chain", chain.provider)
    analytics = leg_analytics(leg, option_type, strike, chain.spot, years, rate)
    if leg.bid and leg.ask and leg.ask >= leg.bid:
        premium, source = (leg.bid + leg.ask) / 2, "bid/ask mid"
    elif leg.ltp:
        premium, source = leg.ltp, "last traded price (no two-sided quote)"
    else:
        raise DataUnavailable(f"{chain.symbol} {strike:g} {option_type}", "no quote or last traded price", chain.provider)
    iv = analytics["iv"] / 100 if analytics and analytics["iv"] is not None else None
    return Leg(option_type, side, float(strike), int(lots), round(float(premium), 2), iv, source)


def _payoff(legs: list[Leg], prices: np.ndarray, lot_size: int) -> np.ndarray:
    total = np.zeros_like(prices, dtype=float)
    for leg in legs:
        intrinsic = np.maximum(prices - leg.strike, 0) if leg.option_type == "CE" else np.maximum(leg.strike - prices, 0)
        total += leg.side * leg.lots * lot_size * (intrinsic - leg.premium)
    return total


def evaluate_strategy(legs: list[Leg], spot: float, lot_size: int, years: float, rate: float, atm_iv: float | None,
                      name: str = "Custom") -> dict:
    if not legs:
        raise ValueError("strategy needs at least one leg")
    if not lot_size:
        raise DataUnavailable("strategy evaluation", "lot size unknown for this instrument", "NSE F&O lot list")
    strikes = [leg.strike for leg in legs]
    low = max(0.01, min(min(strikes), spot) * 0.8)
    high = max(max(strikes), spot) * 1.2
    prices = np.unique(np.concatenate([np.linspace(low, high, 801), np.array(strikes, dtype=float)]))
    expiry_pnl = _payoff(legs, prices, lot_size)

    upper_slope = sum(leg.side * leg.lots for leg in legs if leg.option_type == "CE")
    pnl_at_zero = float(_payoff(legs, np.array([0.0]), lot_size)[0])
    finite = np.concatenate([expiry_pnl, [pnl_at_zero]])
    max_profit: float | str = "unlimited" if upper_slope > 0 else round(float(finite.max()), 2)
    max_loss: float | str = "unlimited" if upper_slope < 0 else round(float(finite.min()), 2)

    breakevens = []
    for i in range(len(prices) - 1):
        a, b = expiry_pnl[i], expiry_pnl[i + 1]
        if a == 0:
            breakevens.append(float(prices[i]))
        elif a * b < 0:
            breakevens.append(float(prices[i] - a * (prices[i + 1] - prices[i]) / (b - a)))
    breakevens = sorted({round(x, 2) for x in breakevens})

    pop = None
    if atm_iv and years > 0:
        sigma, mu = atm_iv, (rate - 0.5 * atm_iv**2) * years
        bounds = [0.0, *breakevens, float("inf")]

        def cdf(x: float) -> float:
            if x <= 0:
                return 0.0
            if x == float("inf"):
                return 1.0
            return _cdf((log(x / spot) - mu) / (sigma * sqrt(years)))

        probability = 0.0
        for lo, hi in zip(bounds, bounds[1:], strict=False):
            probe = (lo + hi) / 2 if hi != float("inf") else (lo * 1.05 if lo > 0 else high)
            if float(_payoff(legs, np.array([probe]), lot_size)[0]) > 0:
                probability += cdf(hi) - cdf(lo)
        pop = round(probability * 100, 1)

    greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    greeks_complete = True
    t0 = np.zeros_like(prices)
    for leg in legs:
        units = leg.side * leg.lots * lot_size
        if leg.iv and years > 0:
            g = option_greeks(spot, leg.strike, years, rate, leg.iv, leg.option_type)
            greeks["delta"] += units * g["delta"]
            greeks["gamma"] += units * g["gamma"]
            greeks["theta"] += units * g["theta_per_day"]
            greeks["vega"] += units * g["vega_per_vol_point"]
            t0 += np.array([units * (bs_price(p, leg.strike, years, rate, leg.iv, leg.option_type) - leg.premium) for p in prices])
        else:
            greeks_complete = False
    net_premium = round(sum(-leg.side * leg.lots * lot_size * leg.premium for leg in legs), 2)
    pick = np.linspace(0, len(prices) - 1, min(161, len(prices))).astype(int)
    reward_risk = None
    if isinstance(max_profit, float) and isinstance(max_loss, float) and max_loss < 0:
        reward_risk = round(max_profit / abs(max_loss), 2)
    return {
        "name": name,
        "legs": [leg.to_dict() for leg in legs],
        "spot": spot,
        "lot_size": lot_size,
        "days_to_expiry": round(years * 365, 2),
        "net_premium": net_premium,
        "premium_type": "credit" if net_premium > 0 else "debit",
        "max_profit": max_profit,
        "max_loss": max_loss,
        "reward_to_risk": reward_risk,
        "breakevens": breakevens,
        "probability_of_profit": pop,
        "pop_basis": f"lognormal expiry distribution with ATM IV {atm_iv * 100:.2f}% (model estimate)" if pop is not None and atm_iv else "unavailable: ATM IV or time to expiry missing",
        "net_greeks": {k: round(v, 4 if k == "gamma" else 2) for k, v in greeks.items()} if greeks_complete else None,
        "greeks_note": None if greeks_complete else "one or more legs lack IV; net Greeks not computed",
        "capital": {
            "premium_paid": abs(net_premium) if net_premium < 0 else 0.0,
            "premium_received": net_premium if net_premium > 0 else 0.0,
            "capital_at_risk": abs(max_loss) if isinstance(max_loss, float) else None,
            "margin": "Data unavailable: SPAN + exposure margin requires a broker margin API"
            if any(leg.side < 0 for leg in legs) else "not applicable (long options only: premium is the capital)",
        },
        "payoff": {
            "prices": [round(float(p), 2) for p in prices[pick]],
            "expiry_pnl": [round(float(v), 2) for v in expiry_pnl[pick]],
            "t0_pnl": [round(float(v), 2) for v in t0[pick]] if greeks_complete else None,
        },
    }


def iv_regime(iv_percentile: dict | None, vix_quote: dict | None) -> dict:
    if iv_percentile:
        value = iv_percentile["value"]
        return {"level": "high" if value >= 60 else "low" if value <= 30 else "normal", "value": value,
                "basis": f"ATM IV percentile {value:.0f} over {iv_percentile['observations']} stored snapshots"}
    if vix_quote and vix_quote.get("year_high") and vix_quote.get("year_low") and vix_quote["year_high"] > vix_quote["year_low"]:
        position = (vix_quote["price"] - vix_quote["year_low"]) / (vix_quote["year_high"] - vix_quote["year_low"]) * 100
        return {"level": "high" if position >= 60 else "low" if position <= 30 else "normal", "value": round(position, 1),
                "basis": f"India VIX {vix_quote['price']:.2f} at {position:.0f}% of its 52-week range"}
    return {"level": "unknown", "value": None, "basis": "no IV history and India VIX range unavailable"}


def suggest_strategies(label: str, direction: int, regime_code: str, iv: dict) -> list[dict]:
    from .signal_engine import LABEL_BEAR, LABEL_BULL

    level = iv["level"]
    out: list[dict] = []

    def add(key: str, why: str) -> None:
        out.append({"key": key, "name": TEMPLATES[key]["name"], "risk": TEMPLATES[key]["risk"], "rationale": why})

    if label in (LABEL_BULL, LABEL_BEAR):
        bull = label == LABEL_BULL
        if level == "high":
            add("bull_put_spread" if bull else "bear_call_spread", f"{'bullish' if bull else 'bearish'} setup with elevated IV ({iv['basis']}): selling premium with defined risk")
            add("bull_call_spread" if bull else "bear_put_spread", "debit spread caps vega exposure if IV falls")
        else:
            add("bull_call_spread" if bull else "bear_put_spread", f"{'bullish' if bull else 'bearish'} setup; IV {level} ({iv['basis']}): defined-risk debit spread")
            if regime_code in ("STRONG_BULLISH_TREND", "STRONG_BEARISH_TREND", "BREAKOUT"):
                add("long_call" if bull else "long_put", "strong trend/breakout regime: outright option keeps uncapped upside; full premium at risk")
    elif regime_code in ("RANGE_BOUND", "LOW_VOLATILITY") and level in ("high", "normal"):
        add("iron_condor", f"range-bound regime with {level} IV: defined-risk premium selling around the range")
        add("iron_butterfly", "tighter range view; higher credit, narrower profit zone")
        if level == "high":
            add("short_strangle", "range view with high IV; UNLIMITED risk, requires margin and active management")
    elif regime_code in ("TRANSITION", "LOW_VOLATILITY", "BREAKOUT") and level == "low":
        add("long_straddle", f"transition/compression with low IV ({iv['basis']}): positions for a volatility expansion")
        add("long_strangle", "cheaper volatility bet; needs a larger move")
    return out
