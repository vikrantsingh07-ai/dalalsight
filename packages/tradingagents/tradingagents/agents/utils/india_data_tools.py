"""LangChain tools for Indian market data: NSE/BSE F&O, delivery, corporate events and flows."""

from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor

_SYMBOL_HELP = (
    "Indian instrument exactly as named in the instrument context: an NSE symbol "
    "(RELIANCE or RELIANCE.NS), an index (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, "
    "SENSEX) or a contract (NIFTY26SEPFUT, NIFTY26SEP23500CE, BANKNIFTY-OPT)"
)


@tool
def get_fno_futures_analysis(
    symbol: Annotated[str, _SYMBOL_HELP],
    curr_date: Annotated[str, "Analysis date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "Number of recent trading sessions to include (2-20)"] = 10,
) -> str:
    """
    Futures positioning for an Indian stock or index from the exchange's end-of-day F&O
    bhavcopy: near- and next-month futures prices, basis and annualised cost of carry, open
    interest in contracts, open-interest build-up (long build-up, short build-up, short
    covering, long unwinding), rollover and lot size. States plainly when the instrument is
    not in the F&O segment.
    """
    return route_to_vendor("get_fno_futures_analysis", symbol, curr_date, look_back_days)


@tool
def get_option_chain_analysis(
    symbol: Annotated[str, _SYMBOL_HELP],
    curr_date: Annotated[str, "Analysis date in yyyy-mm-dd format"],
) -> str:
    """
    Option-chain analysis for an Indian index or stock from the end-of-day F&O bhavcopy, for
    the nearest expiry (or the expiry of the given option contract): put-call ratios, max pain,
    highest call and put open-interest strikes (resistance and support), OI additions and
    reductions, the ATM straddle-implied move, implied volatility per strike, and premium, IV,
    Greeks and breakeven for a specific contract such as NIFTY26SEP23500CE.
    """
    return route_to_vendor("get_option_chain_analysis", symbol, curr_date)


@tool
def get_fii_derivatives_positioning(
    curr_date: Annotated[str, "Analysis date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "Number of recent trading sessions to include (1-10)"] = 5,
) -> str:
    """
    NSE participant-wise open interest: FII, DII, Pro and Client long and short positions in
    index futures, index options and stock futures, with the FII index-futures long % trend
    over recent sessions.
    """
    return route_to_vendor("get_fii_derivatives_positioning", curr_date, look_back_days)


@tool
def get_india_vix(
    curr_date: Annotated[str, "Analysis date in yyyy-mm-dd format"],
) -> str:
    """
    India VIX, the market's expected 30-day NIFTY volatility: latest level, recent changes,
    one-year percentile and range, and the implied NIFTY move.
    """
    return route_to_vendor("get_india_vix", curr_date)


@tool
def get_delivery_analysis(
    symbol: Annotated[str, "NSE stock symbol, e.g. RELIANCE or RELIANCE.NS"],
    curr_date: Annotated[str, "Analysis date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "Number of recent trading sessions to include (3-20)"] = 10,
) -> str:
    """
    NSE security-wise delivery data for a stock: daily close, traded volume, deliverable
    quantity and delivery percentage, with accumulation and distribution signals from price
    moves on above-average delivery.
    """
    return route_to_vendor("get_delivery_analysis", symbol, curr_date, look_back_days)


@tool
def get_corporate_events(
    symbol: Annotated[str, "NSE stock symbol, e.g. RELIANCE or RELIANCE.NS"],
    curr_date: Annotated[str, "Analysis date in yyyy-mm-dd format"],
) -> str:
    """
    NSE corporate events for a stock: dividends, splits, bonus and rights issues with ex-dates,
    board meetings and results dates, and exchange filings from the last 30 days.
    """
    return route_to_vendor("get_corporate_events", symbol, curr_date)


@tool
def get_fii_dii_cash_flows(
    curr_date: Annotated[str, "Analysis date in yyyy-mm-dd format"],
) -> str:
    """
    Latest provisional FII/FPI and DII buy, sell and net values (₹ crore) in the Indian cash
    market, as published by NSE for the most recent session.
    """
    return route_to_vendor("get_fii_dii_cash_flows", curr_date)
