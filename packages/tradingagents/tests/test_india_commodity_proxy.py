"""MCX commodity proxy: USD benchmark x USD/INR converted into MCX units (no network)."""

import pandas as pd
import pytest

from tradingagents.dataflows import y_finance
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.india import commodities


def _frame(values, dates):
    index = pd.DatetimeIndex(pd.to_datetime(dates), name="Date")
    return pd.DataFrame(
        {"Open": values, "High": values, "Low": values, "Close": values, "Volume": [100] * len(values)},
        index=index,
    )


@pytest.fixture
def fake_download(monkeypatch):
    frames = {
        "GC=F": _frame([2000.0, 2010.0, 2020.0], ["2026-09-09", "2026-09-10", "2026-09-11"]),
        # No FX print on 09-10: the 09-09 rate must carry forward.
        "USDINR=X": _frame([80.0, 81.0], ["2026-09-09", "2026-09-11"]),
    }
    monkeypatch.setattr(commodities.yf, "download", lambda symbol, **kwargs: frames[symbol])
    return frames


@pytest.mark.unit
def test_gold_proxy_converts_to_inr_per_10_grams(fake_download):
    proxy = commodities.download_proxy_ohlcv("GOLD.MCX", "2026-09-09", "2026-09-12")
    grams = 10 / 31.1034768
    assert list(proxy.index.strftime("%Y-%m-%d")) == ["2026-09-09", "2026-09-10", "2026-09-11"]
    assert proxy["Close"].iloc[0] == pytest.approx(round(2000.0 * 80.0 * grams, 2))
    assert proxy["Close"].iloc[1] == pytest.approx(round(2010.0 * 80.0 * grams, 2))  # FX carried forward
    assert proxy["Close"].iloc[2] == pytest.approx(round(2020.0 * 81.0 * grams, 2))


@pytest.mark.unit
def test_premium_calibration(fake_download):
    set_config({"mcx_proxy_premium": {"GOLD": 0.06}})
    proxy = commodities.download_proxy_ohlcv("GOLD.MCX", "2026-09-09", "2026-09-12")
    assert proxy["Close"].iloc[0] == pytest.approx(round(2000.0 * 80.0 * 10 / 31.1034768 * 1.06, 2))


@pytest.mark.unit
def test_commodity_without_benchmark_returns_empty(monkeypatch):
    monkeypatch.setattr(commodities.yf, "download", lambda *a, **k: pytest.fail("no download expected"))
    assert commodities.download_proxy_ohlcv("ZINC.MCX", "2026-09-01", "2026-09-12").empty


@pytest.mark.unit
def test_proxy_symbol_detection():
    assert commodities.is_proxy_symbol("gold.mcx")
    assert not commodities.is_proxy_symbol("GC=F")
    assert not commodities.is_proxy_symbol("UNKNOWN.MCX")


@pytest.mark.unit
def test_stock_data_tool_prices_mcx_proxy(fake_download):
    set_config({"market": "india"})
    out = y_finance.get_YFin_data_online("GOLD", "2026-09-09", "2026-09-11")
    assert "GOLD.MCX (from GOLD)" in out
    assert "MCX price proxy" in out
