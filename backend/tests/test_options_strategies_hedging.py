from datetime import timedelta
from math import sqrt

import numpy as np
import pandas as pd
import pytest
from helpers import make_chain, make_ohlcv

from cc.analysis.hedging import beta_stats, hedge_plan
from cc.analysis.options import analyze_chain, buildup, recommend_contracts, years_to_expiry
from cc.analysis.signal_engine import LABEL_BULL, LABEL_NO_TRADE
from cc.analysis.strategies import build_template, evaluate_strategy, iv_regime, suggest_strategies
from cc.config import OptionSettings
from cc.data.models import DataUnavailable, now_ist


def test_chain_metrics():
    chain = make_chain(spot=23410)
    s = analyze_chain(chain, now_ist(), OptionSettings(), None, False)
    call_oi = sum(r.ce.oi for r in chain.rows)
    put_oi = sum(r.pe.oi for r in chain.rows)
    assert s["atm_strike"] == 23400
    assert s["pcr_oi"] == pytest.approx(put_oi / call_oi, rel=1e-3)
    assert s["call_wall"] == 23700 and s["put_wall"] == 23200
    assert s["atm_iv"] == pytest.approx(12.0)
    strikes = np.array(chain.strikes())
    ce = np.array([r.ce.oi for r in chain.rows])
    pe = np.array([r.pe.oi for r in chain.rows])
    payouts = [(ce * np.clip(k - strikes, 0, None)).sum() + (pe * np.clip(strikes - k, 0, None)).sum() for k in strikes]
    assert s["max_pain"] == strikes[int(np.argmin(payouts))]
    years = years_to_expiry(chain.expiry, now_ist())
    assert s["expected_move_1sd"] == pytest.approx(23410 * 0.12 * sqrt(years), rel=0.01)
    atm = next(r for r in s["table"] if r["strike"] == 23400)
    assert 0 < atm["ce"]["delta"] < 1 and -1 < atm["pe"]["delta"] < 0 and atm["ce"]["theta"] < 0


def test_iv_implied_from_mid_when_exchange_iv_missing():
    s = analyze_chain(make_chain(spot=23400, with_iv=False), now_ist(), OptionSettings(), None, False)
    atm = next(r for r in s["table"] if r["strike"] == 23400)
    assert atm["ce"]["iv_source"] == "implied from bid/ask mid"
    assert atm["ce"]["iv"] == pytest.approx(12.0, abs=0.3)


def test_iv_percentile_needs_history():
    chain = make_chain()
    assert analyze_chain(chain, now_ist(), OptionSettings(), [10.0] * 5)["iv_percentile"] is None
    pct = analyze_chain(chain, now_ist(), OptionSettings(), [10.0] * 15 + [14.0] * 15)["iv_percentile"]
    assert pct["value"] == pytest.approx(50.0) and pct["observations"] == 30


def test_buildup_classification():
    assert buildup(5, 100) == "long build-up"
    assert buildup(-5, 100) == "short build-up"
    assert buildup(5, -100) == "short covering"
    assert buildup(-5, -100) == "long unwinding"
    assert buildup(0, 100) is None


def test_contract_recommendations_filter_and_respect_no_trade():
    s = analyze_chain(make_chain(), now_ist(), OptionSettings(), None, False)
    none = recommend_contracts(s, 0, OptionSettings(), 10_000)
    assert none["candidates"] == [] and LABEL_NO_TRADE in none["note"]
    calls = recommend_contracts(s, 1, OptionSettings(), 10_000)
    assert calls["candidates"] and all(0.30 <= c["delta"] <= 0.65 for c in calls["candidates"])
    assert any("delta" in reason for item in calls["rejected"] for reason in item["reasons"])
    top = calls["candidates"][0]
    assert top["breakeven_at_expiry"] == pytest.approx(top["strike"] + top["premium"], abs=0.01)


def test_bull_call_spread_payoff():
    chain = make_chain(spot=23400)
    now = now_ist()
    legs = build_template("bull_call_spread", chain, now, 0.065, lots=1, width_steps=2)
    assert [leg.strike for leg in legs] == [23400, 23500]
    result = evaluate_strategy(legs, chain.spot, 65, years_to_expiry(chain.expiry, now), 0.065, 0.12)
    debit = (legs[0].premium - legs[1].premium) * 65
    assert result["net_premium"] == pytest.approx(-debit, abs=0.05)
    assert result["max_loss"] == pytest.approx(-debit, abs=0.05)
    assert result["max_profit"] == pytest.approx(100 * 65 - debit, abs=0.05)
    assert len(result["breakevens"]) == 1 and result["breakevens"][0] == pytest.approx(23400 + debit / 65, abs=0.2)
    assert 0 < result["probability_of_profit"] < 100
    assert "Data unavailable" in result["capital"]["margin"]  # the short leg needs broker SPAN margin
    long_call = evaluate_strategy(build_template("long_call", chain, now, 0.065), chain.spot, 65,
                                  years_to_expiry(chain.expiry, now), 0.065, 0.12)
    assert long_call["capital"]["margin"].startswith("not applicable") and long_call["max_profit"] == "unlimited"


def test_short_straddle_is_unlimited_risk_and_margin_unavailable():
    chain = make_chain()
    now = now_ist()
    legs = build_template("short_straddle", chain, now, 0.065)
    result = evaluate_strategy(legs, chain.spot, 65, years_to_expiry(chain.expiry, now), 0.065, 0.12)
    assert result["max_loss"] == "unlimited" and result["premium_type"] == "credit"
    assert "Data unavailable" in result["capital"]["margin"]
    assert len(result["breakevens"]) == 2


def test_iron_condor_defined_risk():
    chain = make_chain(n=30)
    now = now_ist()
    legs = build_template("iron_condor", chain, now, 0.065)
    result = evaluate_strategy(legs, chain.spot, 65, years_to_expiry(chain.expiry, now), 0.065, 0.12)
    assert isinstance(result["max_loss"], float) and isinstance(result["max_profit"], float)
    assert len(result["breakevens"]) == 2 and result["breakevens"][0] < chain.spot < result["breakevens"][1]
    assert result["net_greeks"]["theta"] > 0


def test_missing_strike_raises_data_unavailable():
    with pytest.raises(DataUnavailable):
        build_template("iron_condor", make_chain(n=3), now_ist(), 0.065)


def test_strategy_suggestions():
    assert suggest_strategies(LABEL_NO_TRADE, 0, "STRONG_BEARISH_TREND", {"level": "low", "basis": "test"}) == []
    bull_high_iv = suggest_strategies(LABEL_BULL, 1, "WEAK_BULLISH_TREND", {"level": "high", "basis": "test"})
    assert bull_high_iv[0]["key"] == "bull_put_spread"
    assert iv_regime(None, {"price": 12.0, "year_high": 22.0, "year_low": 10.0})["level"] == "low"
    assert iv_regime(None, None)["level"] == "unknown"


def test_beta_recovers_known_beta():
    index = make_ohlcv(300, freq="1D", seed=11)["close"]
    asset = 100 * (1 + 2 * index.pct_change().fillna(0)).cumprod()
    stats = beta_stats(asset, index)
    assert stats["beta"] == pytest.approx(2.0, abs=1e-6) and stats["correlation"] == pytest.approx(1.0, abs=1e-6)
    assert beta_stats(asset.tail(30), index.tail(30)) is None


def test_hedge_plan_futures_puts_and_scenarios():
    monthly = (now_ist() + timedelta(days=30)).date()
    summary = analyze_chain(make_chain(spot=23400, n=60, expiry=monthly), now_ist(), OptionSettings(strikes_around_atm=60), None)
    positions = [{"symbol": "A", "quantity": 1000, "price": 2340.0, "beta": 1.0, "avg_price": None},
                 {"symbol": "B", "quantity": 10, "price": 100.0, "beta": None, "avg_price": 90.0}]
    plan = hedge_plan(positions, "NIFTY", 23400.0, 65, summary)
    assert plan["beta_weighted_exposure"] == pytest.approx(2_340_000)
    assert plan["positions_without_beta"] == ["B"]
    assert plan["futures_hedge"]["action"] == "SELL" and plan["futures_hedge"]["lots"] == 2
    assert [p["strike"] for p in plan["put_hedges"]] == [22700, 22250]
    flat = next(s for s in plan["scenarios"] if s["index_move_pct"] == 0)
    assert flat["with_puts"] == pytest.approx(-plan["put_hedges"][0]["cost"])
    crash = next(s for s in plan["scenarios"] if s["index_move_pct"] == -10)
    assert crash["with_futures"] > crash["unhedged"] and crash["with_puts"] > crash["unhedged"]


def test_hedge_skips_puts_outside_strike_window():
    summary = analyze_chain(make_chain(spot=23400, n=20), now_ist(), OptionSettings(strikes_around_atm=5), None)
    plan = hedge_plan([{"symbol": "A", "quantity": 1000, "price": 2340.0, "beta": 1.0}], "NIFTY", 23400.0, 65, summary)
    assert plan["put_hedges"] == [] and "no quoted put" in plan["put_hedge_note"]
    assert isinstance(pd.DataFrame(plan["scenarios"]), pd.DataFrame)
