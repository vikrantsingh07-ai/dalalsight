"""Regression tests for the bugs found in the 2026-09-13 health check (no network)."""

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest
from langchain_core.messages import AIMessage

from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.utils.agent_utils import EVIDENCE_RULE
from tradingagents.dataflows import stockstats_utils, y_finance
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.india import cash_market, index_history
from tradingagents.llm_clients import openai_client


def _ohlc(dates, close=1.0):
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": 0.0},
        index=pd.DatetimeIndex(pd.to_datetime(dates), name="Date"),
    )


@pytest.mark.unit
def test_stale_or_sparse_nse_index_needs_fallback():
    stale = _ohlc(pd.bdate_range("2025-09-01", "2026-07-17"))
    fresh = _ohlc(pd.bdate_range("2025-09-01", "2026-09-11"))
    sparse = _ohlc(["2026-09-11"])
    assert index_history.needs_nse_index_fallback("NIFTY_FIN_SERVICE.NS", stale, "2025-09-01", "2026-09-13")
    assert index_history.needs_nse_index_fallback("NIFTY_MID_SELECT.NS", sparse, "2025-09-01", "2026-09-13")
    assert not index_history.needs_nse_index_fallback("^NSEI", fresh, "2025-09-01", "2026-09-13")
    assert not index_history.needs_nse_index_fallback("RELIANCE.NS", sparse, "2025-09-01", "2026-09-13")
    assert not index_history.needs_nse_index_fallback("BSE-BANK.BO", sparse, "2025-09-01", "2026-09-13")


@pytest.mark.unit
def test_nse_index_history_is_fetched_in_short_windows(monkeypatch, tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    requested = []

    def fake_api(path, params):
        requested.append((params["from"], params["to"]))
        return [{
            "EOD_TIMESTAMP": "12-SEP-2025", "EOD_OPEN_INDEX_VAL": 1, "EOD_HIGH_INDEX_VAL": 2,
            "EOD_LOW_INDEX_VAL": 0.5, "EOD_CLOSE_INDEX_VAL": 1.5, "HIT_TRADED_QTY": 100,
        }]

    monkeypatch.setattr(index_history, "nse_api_json", fake_api)
    frame = index_history.fetch_nse_index_history("NIFTY FINANCIAL SERVICES", "2025-09-12", "2026-09-11")
    assert len(requested) >= 5  # a year needs several 90-day windows
    for start, end in requested:
        span = (pd.Timestamp(date(int(end[6:]), int(end[3:5]), int(end[:2])))
                - pd.Timestamp(date(int(start[6:]), int(start[3:5]), int(start[:2])))).days
        assert span < 90
    assert list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert frame["Close"].iloc[0] == 1.5 and len(frame) == 1  # duplicates across windows collapse


@pytest.mark.unit
def test_load_ohlcv_rebuilds_stale_index_from_nse(monkeypatch, tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    stale = _ohlc(pd.bdate_range("2021-09-13", "2026-07-17"))
    monkeypatch.setattr(stockstats_utils.yf, "download", lambda *a, **k: stale)
    nse = _ohlc(["2026-09-10", "2026-09-11"], close=25545.4)
    monkeypatch.setattr(stockstats_utils, "nse_index_history_frame", lambda canonical, start, end: nse)
    data = stockstats_utils.load_ohlcv("FINNIFTY", "2026-09-11")
    assert data["Close"].iloc[-1] == 25545.4
    assert data["Date"].iloc[-1] == pd.Timestamp("2026-09-11")


@pytest.mark.unit
def test_quarterly_cash_flow_falls_back_to_annual(monkeypatch):
    ticker = MagicMock()
    ticker.quarterly_cashflow = pd.DataFrame()
    ticker.cashflow = pd.DataFrame({pd.Timestamp("2026-03-31"): [1.0]}, index=["Operating Cash Flow"])
    monkeypatch.setattr(y_finance.yf, "Ticker", lambda symbol: ticker)
    out = y_finance.get_cashflow("RELIANCE.NS", "quarterly", "2026-09-11")
    assert "(annual)" in out and "Quarterly cash flow is not published" in out


@pytest.mark.unit
def test_fii_dii_output_states_coverage(monkeypatch):
    payload = [
        {"category": "DII", "date": "11-Sep-2026", "buyValue": "15109.58", "sellValue": "13141.41", "netValue": "1968.17"},
        {"category": "FII/FPI", "date": "11-Sep-2026", "buyValue": "12616.89", "sellValue": "13547.79", "netValue": "-930.9"},
    ]
    monkeypatch.setattr(cash_market, "nse_api_json", lambda path, params=None: payload)
    out = cash_market.fii_dii_cash_flows("2026-09-11")
    assert "equals 211% of FII/FPI net selling" in out
    assert "more than absorbed" in out


@pytest.mark.unit
def test_bull_prompt_carries_evidence_rule():
    llm = MagicMock()
    llm.invoke.return_value = AIMessage(content="case")
    state = {
        "investment_debate_state": {"history": "", "bull_history": "", "bear_history": "", "current_response": "", "count": 0},
        "market_report": "m", "sentiment_report": "s", "news_report": "n", "fundamentals_report": "f",
        "company_of_interest": "NIFTY", "asset_type": "index",
    }
    create_bull_researcher(llm)(state)
    assert EVIDENCE_RULE in llm.invoke.call_args.args[0]
    assert "{" not in EVIDENCE_RULE


@pytest.mark.unit
def test_transient_upstream_error_is_retried(monkeypatch):
    calls = {"n": 0}

    def flaky(self, input, config=None, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError({"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502})
        return AIMessage(content="ok")

    monkeypatch.setattr(openai_client.ChatOpenAI, "invoke", flaky)
    monkeypatch.setattr(openai_client.time, "sleep", lambda seconds: None)
    llm = openai_client.NormalizedChatOpenAI(model="nvidia/test", api_key="placeholder")
    assert llm.invoke("hi").content == "ok"
    assert calls["n"] == 3


@pytest.mark.unit
def test_non_transient_error_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def broken(self, input, config=None, **kwargs):
        calls["n"] += 1
        raise ValueError("invalid request: unknown parameter")

    monkeypatch.setattr(openai_client.ChatOpenAI, "invoke", broken)
    llm = openai_client.NormalizedChatOpenAI(model="nvidia/test", api_key="placeholder")
    with pytest.raises(ValueError):
        llm.invoke("hi")
    assert calls["n"] == 1
