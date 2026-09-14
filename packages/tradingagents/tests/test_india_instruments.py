"""Indian instrument parsing, symbol resolution, instrument context and CLI classification."""

import pytest

from cli.models import AnalystType, AssetType
from cli.utils import (
    detect_asset_type,
    filter_analysts_for_asset_type,
    is_valid_ticker_input,
    normalize_ticker_symbol,
)
from tradingagents.agents.utils.agent_utils import build_instrument_context
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.india.instruments import (
    COMMODITY,
    CURRENCY,
    EQUITY,
    FUTURES,
    INDEX,
    OPTIONS,
    parse_indian_symbol,
)
from tradingagents.dataflows.symbol_utils import normalize_symbol, reference_symbol
from tradingagents.default_config import (
    DEFAULT_CONFIG,
    GLOBAL_NEWS_QUERIES,
    INDIA_NEWS_QUERIES,
    apply_market_preset,
)


@pytest.fixture
def india_mode():
    set_config({"market": "india"})


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,segment,underlying,price_symbol",
    [
        ("RELIANCE.NS", EQUITY, "RELIANCE", "RELIANCE.NS"),
        ("500325.BO", EQUITY, "500325", "500325.BO"),
        ("M&M.NS", EQUITY, "M&M", "M&M.NS"),
        ("NIFTY", INDEX, "NIFTY", "^NSEI"),
        ("nifty50", INDEX, "NIFTY", "^NSEI"),
        ("^NSEBANK", INDEX, "BANKNIFTY", "^NSEBANK"),
        ("SENSEX", INDEX, "SENSEX", "^BSESN"),
        ("INDIAVIX", INDEX, "INDIAVIX", "^INDIAVIX"),
        ("NIFTY26SEPFUT", FUTURES, "NIFTY", "^NSEI"),
        ("BAJAJ-AUTO26OCTFUT", FUTURES, "BAJAJ-AUTO", "BAJAJ-AUTO.NS"),
        ("RELIANCE-FUT", FUTURES, "RELIANCE", "RELIANCE.NS"),
        ("NIFTY26SEP23500CE", OPTIONS, "NIFTY", "^NSEI"),
        ("NIFTY2691523500PE", OPTIONS, "NIFTY", "^NSEI"),
        ("FINNIFTY26D2925000CE", OPTIONS, "FINNIFTY", "NIFTY_FIN_SERVICE.NS"),
        ("NIFTYNXT5026SEP70000CE", OPTIONS, "NIFTYNXT50", "^NSMIDCP"),
        ("BANKNIFTY-OPT", OPTIONS, "BANKNIFTY", "^NSEBANK"),
        ("GOLD.MCX", COMMODITY, "GOLD", "GOLD.MCX"),
        ("CRUDEOIL26SEPFUT", COMMODITY, "CRUDEOIL", "CRUDEOIL.MCX"),
        ("USDINR", CURRENCY, "USDINR", "USDINR=X"),
        ("USDINR26SEPFUT", CURRENCY, "USDINR", "USDINR=X"),
    ],
)
def test_indian_symbols_parse_in_every_mode(raw, segment, underlying, price_symbol):
    inst = parse_indian_symbol(raw, india_mode=False)
    assert inst is not None
    assert (inst.segment, inst.underlying, inst.price_symbol) == (segment, underlying, price_symbol)
    # The data layer prices the same instrument the parser resolved.
    assert normalize_symbol(raw) == price_symbol


@pytest.mark.unit
def test_contract_fields():
    weekly = parse_indian_symbol("NIFTY2691523500PE", india_mode=False)
    assert (weekly.expiry_year, weekly.expiry_month, weekly.expiry_day) == (2026, 9, 15)
    assert (weekly.strike, weekly.option_type, weekly.contract) == (23500, "PE", "OPT")

    monthly = parse_indian_symbol("RELIANCE26NOV1360CE", india_mode=False)
    assert (monthly.expiry_year, monthly.expiry_month, monthly.expiry_day) == (2026, 11, None)
    assert monthly.strike == 1360 and monthly.fno_exchange == "NSE"

    assert parse_indian_symbol("SENSEX26OCTFUT", india_mode=False).fno_exchange == "BSE"
    assert parse_indian_symbol("NIFTY-FUT", india_mode=False).expiry_label() == "nearest listed expiry"


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw", ["AAPL", "GOLD", "GC=F", "BTCUSD", "EURUSD", "BRK-B", "0700.HK", "SPX500", "NIFTYIT-FUT"]
)
def test_non_indian_symbols_outside_india_mode(raw):
    assert parse_indian_symbol(raw, india_mode=False) is None


@pytest.mark.unit
def test_india_mode_resolves_bare_symbols(india_mode):
    assert normalize_symbol("RELIANCE") == "RELIANCE.NS"
    assert normalize_symbol("GOLD") == "GOLD.MCX"
    assert reference_symbol("GOLD") == "GC=F"
    # Global symbols keep their meaning even in India mode.
    assert normalize_symbol("BTCUSD") == "BTC-USD"
    assert normalize_symbol("EURUSD") == "EURUSD=X"
    assert normalize_symbol("^GSPC") == "^GSPC"
    assert normalize_symbol("XAUUSD") == "GC=F"


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,symbol,asset_type",
    [
        ("NIFTY26SEPFUT", "NIFTY26SEPFUT", AssetType.FUTURES),
        ("banknifty-opt", "BANKNIFTY-OPT", AssetType.OPTIONS),
        ("^NSEI", "NIFTY", AssetType.INDEX),
        ("RELIANCE.NS", "RELIANCE.NS", AssetType.STOCK),
        ("USDINR", "USDINR", AssetType.CURRENCY),
        ("GOLD.MCX", "GOLD.MCX", AssetType.COMMODITY),
    ],
)
def test_cli_keeps_indian_instrument_and_detects_segment(raw, symbol, asset_type):
    assert normalize_ticker_symbol(raw) == symbol
    assert detect_asset_type(raw) == asset_type


@pytest.mark.unit
def test_cli_accepts_ampersand_symbols():
    assert is_valid_ticker_input("M&M.NS")


_ALL_ANALYSTS = [
    AnalystType.MARKET,
    AnalystType.SOCIAL,
    AnalystType.NEWS,
    AnalystType.FUNDAMENTALS,
    AnalystType.DERIVATIVES,
]


@pytest.mark.unit
def test_derivatives_analyst_offered_only_with_exchange_fno():
    assert AnalystType.DERIVATIVES in filter_analysts_for_asset_type(_ALL_ANALYSTS, AssetType.INDEX, "NIFTY")
    assert AnalystType.DERIVATIVES in filter_analysts_for_asset_type(_ALL_ANALYSTS, AssetType.STOCK, "RELIANCE.NS")
    assert AnalystType.DERIVATIVES in filter_analysts_for_asset_type(_ALL_ANALYSTS, AssetType.OPTIONS, "NIFTY-OPT")
    assert AnalystType.DERIVATIVES not in filter_analysts_for_asset_type(_ALL_ANALYSTS, AssetType.STOCK, "AAPL")
    assert AnalystType.DERIVATIVES not in filter_analysts_for_asset_type(_ALL_ANALYSTS, AssetType.INDEX, "NIFTYIT")
    assert AnalystType.DERIVATIVES not in filter_analysts_for_asset_type(_ALL_ANALYSTS, AssetType.STOCK)


@pytest.mark.unit
@pytest.mark.parametrize("asset_type,ticker", [(AssetType.COMMODITY, "GOLD.MCX"), (AssetType.CURRENCY, "USDINR")])
def test_no_fundamentals_or_derivatives_for_mcx_and_currency(asset_type, ticker):
    kept = filter_analysts_for_asset_type(_ALL_ANALYSTS, asset_type, ticker)
    assert AnalystType.FUNDAMENTALS not in kept
    assert AnalystType.DERIVATIVES not in kept


@pytest.mark.unit
def test_option_contract_context_explains_premium_and_contract():
    context = build_instrument_context(
        "NIFTY26SEP23500CE",
        "options",
        {"company_name": "NIFTY 50"},
        {"as_of": "2026-09-11", "expiry": "2026-09-29", "days_to_expiry": 18, "lot_size": 65},
    )
    assert "Name: NIFTY 50" in context
    assert "PREMIUM" in context
    assert "lot size 65" in context and "2026-09-29" in context
    assert "INR" in context


@pytest.mark.unit
def test_mcx_context_discloses_proxy():
    context = build_instrument_context("GOLD.MCX", "commodity")
    assert "PROXY" in context and "GC=F" in context and "INR per 10 grams" in context


@pytest.mark.unit
def test_context_unchanged_for_other_markets():
    assert "Market: India" not in build_instrument_context("AAPL")


@pytest.mark.unit
def test_india_preset_switches_news_and_index_fundamentals():
    config = apply_market_preset({**DEFAULT_CONFIG, "market": "india"})
    assert config["global_news_queries"] == INDIA_NEWS_QUERIES
    assert config["data_vendors"]["fundamental_data"] == "nse,yfinance"
    # The shared default dict is not mutated through the shallow copy.
    assert DEFAULT_CONFIG["data_vendors"]["fundamental_data"] == "yfinance"
    assert DEFAULT_CONFIG["global_news_queries"] == GLOBAL_NEWS_QUERIES


@pytest.mark.unit
def test_india_preset_keeps_explicit_choices():
    config = apply_market_preset(
        {"market": "india", "global_news_queries": ["custom"], "data_vendors": {"fundamental_data": "alpha_vantage"}}
    )
    assert config["global_news_queries"] == ["custom"]
    assert config["data_vendors"]["fundamental_data"] == "alpha_vantage"


@pytest.mark.unit
def test_global_preset_is_a_no_op():
    config = {"market": "global", "global_news_queries": ["x"]}
    assert apply_market_preset(config) == {"market": "global", "global_news_queries": ["x"]}
