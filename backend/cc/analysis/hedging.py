"""Portfolio hedging engine: beta-weighted exposure, index futures and put/collar hedges, scenarios.

Betas are regressions of daily returns (up to one year) against the hedge index. Option costs
come from the live chain. The public feed has no index futures quote, so the index spot is
used as the futures price proxy (basis ignored) and this is stated in the result.
"""

from __future__ import annotations

from math import ceil
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, field_validator

from ..data.symbols import SYMBOL_RE


class PositionIn(BaseModel):
    symbol: str = Field(max_length=32)
    kind: Literal["stock", "future"] = "stock"
    quantity: float
    avg_price: float | None = Field(None, gt=0)

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not SYMBOL_RE.match(value):
            raise ValueError("invalid symbol")
        return value

    @field_validator("quantity")
    @classmethod
    def _qty(cls, value: float) -> float:
        if value == 0 or abs(value) > 1e9:
            raise ValueError("quantity must be non-zero and realistic")
        return value


class HedgeRequest(BaseModel):
    positions: list[PositionIn] = Field(min_length=1, max_length=50)
    hedge_index: Literal["NIFTY", "BANKNIFTY"] = "NIFTY"
    put_moneyness: list[float] = Field(default_factory=lambda: [0.97, 0.95], max_length=4)
    call_moneyness: float = Field(1.03, gt=1, le=1.3)


def beta_stats(asset_close: pd.Series, index_close: pd.Series, lookback: int = 250) -> dict | None:
    a = pd.Series(asset_close.to_numpy(dtype=float), index=pd.Index(asset_close.index.date))
    b = pd.Series(index_close.to_numpy(dtype=float), index=pd.Index(index_close.index.date))
    a, b = a[~a.index.duplicated(keep="last")], b[~b.index.duplicated(keep="last")]
    joined = pd.concat([a.pct_change(), b.pct_change()], axis=1, join="inner").dropna().tail(lookback)
    if len(joined) < 60:
        return None
    x, y = joined.iloc[:, 1].to_numpy(), joined.iloc[:, 0].to_numpy()
    var = float(np.var(x, ddof=1))
    if var <= 0:
        return None
    beta = float(np.cov(y, x, ddof=1)[0, 1] / var)
    corr = float(np.corrcoef(y, x)[0, 1])
    return {"beta": round(beta, 3), "correlation": round(corr, 3), "r_squared": round(corr**2, 3), "observations": len(joined),
            "basis": f"daily returns regression over {len(joined)} sessions"}


def hedge_plan(positions: list[dict], index_symbol: str, index_spot: float, lot_size: int | None,
               chain_summary: dict | None, put_moneyness: list[float] | tuple[float, ...] = (0.97, 0.95),
               call_moneyness: float = 1.03) -> dict:
    """positions: dicts with symbol, quantity, price, beta (or None) — prices already fetched."""
    rows = []
    for p in positions:
        value = p["quantity"] * p["price"]
        beta = p.get("beta")
        rows.append({**p, "value": round(value, 2), "beta_exposure": None if beta is None else round(value * beta, 2),
                     "pnl": None if not p.get("avg_price") else round((p["price"] - p["avg_price"]) * p["quantity"], 2)})
    covered = [r for r in rows if r["beta_exposure"] is not None]
    missing = [r["symbol"] for r in rows if r["beta_exposure"] is None]
    gross = sum(abs(r["value"]) for r in rows)
    net = sum(r["value"] for r in rows)
    exposure = sum(r["beta_exposure"] for r in covered)
    index_units = exposure / index_spot
    result: dict = {
        "positions": rows,
        "gross_value": round(gross, 2),
        "net_value": round(net, 2),
        "beta_weighted_exposure": round(exposure, 2),
        "portfolio_beta": round(exposure / net, 3) if net else None,
        "index": index_symbol,
        "index_spot": index_spot,
        "index_units_equivalent": round(index_units, 2),
        "positions_without_beta": missing,
        "assumptions": [
            "beta from daily-return regression against the hedge index (≤ 250 sessions)",
            "index spot used as the futures price proxy; futures basis and rollover cost ignored",
            "scenario P&L uses beta × index move (linear) and option payoffs at expiry",
            "SPAN margin for futures/short options requires a broker margin API (not included)",
        ],
    }
    if not lot_size:
        result["futures_hedge"] = {"status": "unavailable", "reason": "lot size unknown"}
        return result

    lots = round(index_units / lot_size)
    futures = {
        "action": "SELL" if lots > 0 else "BUY" if lots < 0 else "NONE",
        "lots": abs(lots),
        "lot_size": lot_size,
        "notional": round(abs(lots) * lot_size * index_spot, 2),
        "residual_exposure": round(exposure - lots * lot_size * index_spot, 2),
        "hedge_ratio": round(lots * lot_size * index_spot / exposure, 3) if exposure else None,
    }
    result["futures_hedge"] = futures

    put_hedges, collar = [], None
    if chain_summary and exposure > 0:
        table = chain_summary["table"]
        step = chain_summary.get("strike_step") or 0
        put_lots = ceil(index_units / lot_size)
        skipped = []
        for moneyness in put_moneyness:
            target = index_spot * moneyness
            row = min((r for r in table if r["pe"] and r["pe"]["mid"]), key=lambda r: abs(r["strike"] - target), default=None)
            if row is None or (step and abs(row["strike"] - target) > step):
                skipped.append(f"{moneyness * 100:g}% of spot ({target:,.0f}) has no quoted put within one strike step")
                continue
            premium = row["pe"]["mid"]
            cost = premium * put_lots * lot_size
            put_hedges.append({
                "strike": row["strike"], "moneyness_pct": round(row["strike"] / index_spot * 100, 2), "premium": premium,
                "lots": put_lots, "cost": round(cost, 2), "cost_pct_of_exposure": round(cost / exposure * 100, 3),
                "iv": row["pe"]["iv"], "oi": row["pe"]["oi"], "expiry": chain_summary["expiry"],
            })
        if skipped:
            result["put_hedge_note"] = "; ".join(skipped)
        call_target = index_spot * call_moneyness
        call_row = min((r for r in table if r["ce"] and r["ce"]["mid"] and r["strike"] > index_spot),
                       key=lambda r: abs(r["strike"] - call_target), default=None)
        if put_hedges and call_row:
            put = put_hedges[0]
            credit = call_row["ce"]["mid"] * put_lots * lot_size
            collar = {"put_strike": put["strike"], "call_strike": call_row["strike"], "lots": put_lots,
                      "put_cost": put["cost"], "call_credit": round(credit, 2), "net_cost": round(put["cost"] - credit, 2),
                      "expiry": chain_summary["expiry"], "note": "caps upside above the call strike"}
    elif exposure <= 0:
        result["put_hedge_note"] = "net beta exposure is not long; protective puts do not apply"
    else:
        result["put_hedge_note"] = "option chain unavailable for put pricing"
    result["put_hedges"] = put_hedges
    result["collar"] = collar

    scenarios = []
    for move in (-10, -5, -3, -1, 0, 1, 3, 5, 10):
        m = move / 100
        index_after = index_spot * (1 + m)
        unhedged = exposure * m
        entry = {"index_move_pct": move, "index_level": round(index_after, 2), "unhedged": round(unhedged, 2),
                 "with_futures": round(unhedged - lots * lot_size * index_spot * m, 2)}
        if put_hedges:
            put = put_hedges[0]
            put_value = max(0.0, put["strike"] - index_after) * put["lots"] * lot_size
            entry["with_puts"] = round(unhedged + put_value - put["cost"], 2)
            if collar:
                call_loss = max(0.0, index_after - collar["call_strike"]) * collar["lots"] * lot_size
                entry["with_collar"] = round(unhedged + put_value - put["cost"] - call_loss + collar["call_credit"], 2)
        scenarios.append(entry)
    result["scenarios"] = scenarios
    return result
