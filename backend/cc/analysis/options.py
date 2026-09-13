"""Option-chain analytics for NSE chains.

Every input comes from the exchange chain: OI, volume, bid/ask and IV as published by NSE.
Greeks use Black-Scholes with the NSE IV for that strike, or IV implied from the bid/ask mid
when NSE publishes none; the IV source is tagged on every leg. Nothing is interpolated or invented.
"""

from __future__ import annotations

from datetime import date, datetime, time
from math import floor, log10, sqrt
from typing import Any

import numpy as np
import pandas as pd
from tradingagents.dataflows.india.fno import implied_volatility, max_pain_strike, option_greeks

from ..config import OptionSettings
from ..data.models import IST, OptionChain, OptionLeg

EXPIRY_TIME = time(15, 30)
YEAR_SECONDS = 365.0 * 86400


def years_to_expiry(expiry: date, now: datetime) -> float:
    expiry_dt = datetime.combine(expiry, EXPIRY_TIME, IST)
    return max((expiry_dt - now.astimezone(IST)).total_seconds(), 0.0) / YEAR_SECONDS


def buildup(price_change: float | None, oi_change: float | None) -> str | None:
    if not price_change or not oi_change:
        return None
    if price_change > 0 and oi_change > 0:
        return "long build-up"
    if price_change < 0 < oi_change:
        return "short build-up"
    if price_change > 0 > oi_change:
        return "short covering"
    return "long unwinding"


def leg_analytics(leg: OptionLeg | None, side: str, strike: float, spot: float, years: float, rate: float) -> dict | None:
    if leg is None:
        return None
    mid = leg.mid
    iv: float | None = None
    iv_source = None
    if leg.iv:
        iv, iv_source = leg.iv / 100, "NSE"
    elif mid and years > 0:
        implied = implied_volatility(mid, spot, strike, years, rate, side)
        if implied:
            iv, iv_source = implied, "implied from bid/ask mid"
    greeks = option_greeks(spot, strike, years, rate, iv, side) if iv and years > 0 else None
    intrinsic = max(0.0, spot - strike) if side == "CE" else max(0.0, strike - spot)
    return {
        "ltp": leg.ltp,
        "bid": leg.bid,
        "ask": leg.ask,
        "mid": None if mid is None else round(mid, 2),
        "spread_pct": None if leg.spread_pct is None else round(leg.spread_pct, 2),
        "change": leg.change,
        "change_pct": None if leg.change_pct is None else round(leg.change_pct, 2),
        "volume": leg.volume,
        "oi": leg.oi,
        "oi_change": leg.oi_change,
        "oi_change_pct": None if leg.oi_change_pct is None else round(leg.oi_change_pct, 2),
        "iv": None if iv is None else round(iv * 100, 2),
        "iv_source": iv_source,
        "delta": None if greeks is None else round(greeks["delta"], 4),
        "gamma": None if greeks is None else round(greeks["gamma"], 6),
        "theta": None if greeks is None else round(greeks["theta_per_day"], 2),
        "vega": None if greeks is None else round(greeks["vega_per_vol_point"], 2),
        "intrinsic": round(intrinsic, 2),
        "time_value": None if mid is None else round(mid - intrinsic, 2),
        "buildup": buildup(leg.change, leg.oi_change),
    }


def _leg_sum(rows: list[dict], side: str, field: str) -> float:
    return float(sum((row[side] or {}).get(field) or 0.0 for row in rows))


def _top(rows: list[dict], side: str, field: str, count: int = 3, positive_only: bool = False) -> list[dict]:
    items = [
        {"strike": row["strike"], field: row[side][field], "oi": row[side]["oi"], "oi_change": row[side]["oi_change"]}
        for row in rows
        if row[side] and row[side].get(field) is not None and (not positive_only or row[side][field] > 0)
    ]
    return sorted(items, key=lambda item: -item[field])[:count]


def analyze_chain(chain: OptionChain, now: datetime, settings: OptionSettings, iv_history: list[float] | None = None,
                  is_trading: bool = False) -> dict:
    years = years_to_expiry(chain.expiry, now)
    rate, spot = settings.risk_free_rate, chain.spot
    rows: list[dict[str, Any]] = [
        {
            "strike": row.strike,
            "ce": leg_analytics(row.ce, "CE", row.strike, spot, years, rate),
            "pe": leg_analytics(row.pe, "PE", row.strike, spot, years, rate),
        }
        for row in chain.rows
    ]
    call_oi, put_oi = _leg_sum(rows, "ce", "oi"), _leg_sum(rows, "pe", "oi")
    call_vol, put_vol = _leg_sum(rows, "ce", "volume"), _leg_sum(rows, "pe", "volume")
    call_chg, put_chg = _leg_sum(rows, "ce", "oi_change"), _leg_sum(rows, "pe", "oi_change")

    oi_frame = pd.DataFrame(
        {"ce_oi": [(r["ce"] or {}).get("oi") or 0.0 for r in rows], "pe_oi": [(r["pe"] or {}).get("oi") or 0.0 for r in rows]},
        index=[r["strike"] for r in rows],
    )
    max_pain = max_pain_strike(oi_frame) if (call_oi + put_oi) > 0 else None

    above = [r for r in rows if r["strike"] >= spot]
    below = [r for r in rows if r["strike"] <= spot]
    call_wall = _top(above, "ce", "oi", 1)
    put_wall = _top(below, "pe", "oi", 1)

    atm = chain.atm_strike()
    atm_row = next((r for r in rows if r["strike"] == atm), None)
    straddle = atm_iv = None
    if atm_row and atm_row["ce"] and atm_row["pe"]:
        if atm_row["ce"]["mid"] is not None and atm_row["pe"]["mid"] is not None:
            straddle = round(atm_row["ce"]["mid"] + atm_row["pe"]["mid"], 2)
        ivs = [leg["iv"] for leg in (atm_row["ce"], atm_row["pe"]) if leg["iv"] is not None]
        atm_iv = round(float(np.mean(ivs)), 2) if ivs else None
    expected_move = round(spot * atm_iv / 100 * sqrt(years), 2) if atm_iv and years > 0 else None

    skew = None
    if expected_move:
        put_row = min(below or rows, key=lambda r: abs(r["strike"] - (spot - expected_move)))
        call_row = min(above or rows, key=lambda r: abs(r["strike"] - (spot + expected_move)))
        put_iv = (put_row["pe"] or {}).get("iv")
        call_iv = (call_row["ce"] or {}).get("iv")
        if put_iv is not None and call_iv is not None:
            skew = {
                "put_strike": put_row["strike"], "put_iv": put_iv, "call_strike": call_row["strike"], "call_iv": call_iv,
                "skew_vol_points": round(put_iv - call_iv, 2),
                "basis": "OTM put IV minus OTM call IV at strikes ≈ 1 expected move from spot",
            }

    iv_percentile = None
    if atm_iv is not None and iv_history and len(iv_history) >= 20:
        iv_percentile = {"value": round(float((np.array(iv_history) <= atm_iv).mean() * 100), 1), "observations": len(iv_history)}

    strikes = [r["strike"] for r in rows]
    table = rows
    if atm is not None:
        centre = strikes.index(atm)
        table = rows[max(0, centre - settings.strikes_around_atm): centre + settings.strikes_around_atm + 1]

    age_seconds = (now - chain.timestamp).total_seconds()
    pcr_oi = round(put_oi / call_oi, 3) if call_oi else None
    summary = {
        "symbol": chain.symbol,
        "expiry": chain.expiry.isoformat(),
        "days_to_expiry": round(years * 365, 2),
        "spot": spot,
        "timestamp": chain.timestamp.isoformat(),
        "provider": chain.provider,
        "age_seconds": round(age_seconds),
        "stale": bool(is_trading and age_seconds > 300),
        "lot_size": chain.lot_size,
        "strike_step": chain.strike_step(),
        "atm_strike": atm,
        "atm_iv": atm_iv,
        "atm_straddle": straddle,
        "expected_move_1sd": expected_move,
        "expected_range": [round(spot - expected_move, 2), round(spot + expected_move, 2)] if expected_move else None,
        "expected_move_basis": "spot × ATM IV × √(time to expiry); one standard deviation under Black-Scholes",
        "iv_skew": skew,
        "iv_percentile": iv_percentile,
        "iv_percentile_note": None if iv_percentile else "needs ≥ 20 stored daily ATM IV snapshots for this symbol",
        "totals": {"call_oi": call_oi, "put_oi": put_oi, "call_volume": call_vol, "put_volume": put_vol,
                   "call_oi_change": call_chg, "put_oi_change": put_chg},
        "pcr_oi": pcr_oi,
        "pcr_volume": round(put_vol / call_vol, 3) if call_vol else None,
        "max_pain": max_pain,
        "call_wall": call_wall[0]["strike"] if call_wall else None,
        "put_wall": put_wall[0]["strike"] if put_wall else None,
        "top_call_oi": _top(rows, "ce", "oi"),
        "top_put_oi": _top(rows, "pe", "oi"),
        "top_call_oi_added": _top(rows, "ce", "oi_change", positive_only=True),
        "top_put_oi_added": _top(rows, "pe", "oi_change", positive_only=True),
        "table": table,
        "risk_free_rate": rate,
    }
    summary["interpretation"] = interpret(summary)
    return summary


def interpret(s: dict) -> list[str]:
    notes = []
    pcr = s["pcr_oi"]
    if pcr is not None:
        tone = "put-heavy open interest" if pcr > 1.2 else "call-heavy open interest" if pcr < 0.8 else "balanced open interest"
        notes.append(f"PCR (OI) {pcr:.2f}: {tone}.")
    if s["put_wall"] is not None:
        notes.append(f"Highest put OI at or below spot: {s['put_wall']:g} (support reference from put writers).")
    if s["call_wall"] is not None:
        notes.append(f"Highest call OI at or above spot: {s['call_wall']:g} (resistance reference from call writers).")
    if s["top_call_oi_added"]:
        top = s["top_call_oi_added"][0]
        notes.append(f"Largest call OI addition today: {top['strike']:g} (+{top['oi_change']:,.0f}).")
    if s["top_put_oi_added"]:
        top = s["top_put_oi_added"][0]
        notes.append(f"Largest put OI addition today: {top['strike']:g} (+{top['oi_change']:,.0f}).")
    if s["max_pain"] is not None:
        notes.append(f"Max pain {s['max_pain']:g} vs spot {s['spot']:,.2f}.")
    if s["expected_range"]:
        low, high = s["expected_range"]
        notes.append(f"1-SD expected range to expiry from ATM IV {s['atm_iv']:.2f}%: {low:,.2f} – {high:,.2f}.")
    return notes


def signal_input(summary: dict) -> dict:
    totals = summary["totals"]
    return {
        "pcr_oi": summary["pcr_oi"],
        "call_oi_change": totals["call_oi_change"],
        "put_oi_change": totals["put_oi_change"],
        "call_wall": summary["call_wall"],
        "put_wall": summary["put_wall"],
    }


def recommend_contracts(summary: dict, direction: int, settings: OptionSettings, risk_capital: float) -> dict:
    """Rank liquid strikes for a directional view. Returns rejected strikes with reasons as well."""
    if direction == 0:
        return {"side": None, "candidates": [], "rejected": [], "note": "No directional setup: NO TRADE / WAIT FOR CONFIRMATION."}
    side = "ce" if direction > 0 else "pe"
    lot = summary.get("lot_size")
    candidates, rejected = [], []
    for row in summary["table"]:
        leg = row[side]
        if not leg:
            continue
        reasons = []
        delta = abs(leg["delta"]) if leg["delta"] is not None else None
        if leg["mid"] is None:
            reasons.append("no price")
        if delta is None:
            reasons.append("no IV, Greeks unavailable")
        elif not settings.delta_min <= delta <= settings.delta_max:
            reasons.append(f"|delta| {delta:.2f} outside {settings.delta_min}–{settings.delta_max}")
        if (leg["oi"] or 0) < settings.min_oi:
            reasons.append(f"OI {leg['oi'] or 0:,.0f} below {settings.min_oi:,.0f}")
        if (leg["volume"] or 0) < settings.min_volume:
            reasons.append(f"volume {leg['volume'] or 0:,.0f} below {settings.min_volume:,.0f}")
        if leg["spread_pct"] is None:
            reasons.append("no two-sided quote")
        elif leg["spread_pct"] > settings.max_spread_pct:
            reasons.append(f"bid-ask spread {leg['spread_pct']:.1f}% above {settings.max_spread_pct}%")
        if reasons or delta is None:
            rejected.append({"strike": row["strike"], "reasons": reasons})
            continue
        premium = leg["mid"]
        liquidity = 0.5 * min(1.0, log10(leg["oi"] + 1) / 6) + 0.5 * min(1.0, log10(leg["volume"] + 1) / 7)
        delta_fit = 1 - abs(delta - 0.5) / 0.5
        spread_score = 1 - leg["spread_pct"] / settings.max_spread_pct
        theta_burden = abs(leg["theta"] or 0) / premium if premium else 1.0
        score = 40 * delta_fit + 30 * liquidity + 20 * spread_score + 10 * (1 - min(1.0, theta_burden * 10))
        per_lot = premium * lot if lot else None
        candidates.append({
            "strike": row["strike"],
            "option_type": side.upper(),
            "premium": premium,
            "bid": leg["bid"],
            "ask": leg["ask"],
            "spread_pct": leg["spread_pct"],
            "iv": leg["iv"],
            "delta": leg["delta"],
            "gamma": leg["gamma"],
            "theta": leg["theta"],
            "vega": leg["vega"],
            "oi": leg["oi"],
            "volume": leg["volume"],
            "breakeven_at_expiry": round(row["strike"] + premium if direction > 0 else row["strike"] - premium, 2),
            "premium_per_lot": None if per_lot is None else round(per_lot, 2),
            "max_loss_per_lot": None if per_lot is None else round(per_lot, 2),
            "theta_per_lot_per_day": None if (lot is None or leg["theta"] is None) else round(leg["theta"] * lot, 2),
            "lots_within_risk_budget": None if not per_lot else floor(risk_capital / per_lot),
            "score": round(score, 1),
        })
    candidates.sort(key=lambda c: -c["score"])
    return {
        "side": side.upper(),
        "candidates": candidates[:3],
        "rejected": rejected,
        "score_basis": "40% delta closeness to 0.50, 30% OI and volume, 20% bid-ask spread, 10% theta burden",
        "risk_note": "Buying options risks the full premium. Risk budget = capital × risk per trade.",
    }
