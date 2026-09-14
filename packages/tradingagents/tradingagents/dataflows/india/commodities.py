"""MCX commodity price proxy built from global futures and USD/INR.

MCX blocks automated access to its market data and no free feed carries MCX
contract prices. So the price and indicator tools still work on MCX
commodities, a daily OHLCV proxy is synthesized:

    proxy = global benchmark future (USD) x USDINR x unit conversion x (1 + premium)

e.g. MCX GOLD (INR per 10 g) = COMEX GC=F (USD / troy oz) x USDINR x 10 / 31.1035.

The proxy tracks MCX trend and percentage moves closely but omits import duty,
GST and local premiums, so absolute levels differ. ``mcx_proxy_premium`` in the
config calibrates a per-commodity premium (e.g. ``{"GOLD": 0.06}``), and the
instrument context tells agents to state levels as percentage distances.
"""

from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

from ..config import get_config
from .instruments import COMMODITIES

logger = logging.getLogger(__name__)

PROXY_SUFFIX = ".MCX"
_USDINR = "USDINR=X"
_OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def proxy_code(symbol: str) -> str | None:
    """The MCX commodity code for a proxy symbol like ``GOLD.MCX``, else None."""
    if not isinstance(symbol, str):
        return None
    s = symbol.strip().upper()
    if not s.endswith(PROXY_SUFFIX):
        return None
    code = s[: -len(PROXY_SUFFIX)]
    return code if code in COMMODITIES else None


def is_proxy_symbol(symbol: str) -> bool:
    return proxy_code(symbol) is not None


def _daily(frame: pd.DataFrame | None) -> pd.DataFrame:
    """Naive, midnight-normalized, de-duplicated daily index."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=_OHLCV)
    frame = frame.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    index = pd.to_datetime(frame.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    frame.index = index.normalize()
    return frame[~frame.index.duplicated(keep="last")].sort_index()


def _premium(code: str) -> float:
    table = get_config().get("mcx_proxy_premium") or {}
    try:
        return float(table.get(code, 0.0))
    except (TypeError, ValueError):
        logger.warning("Ignoring non-numeric mcx_proxy_premium for %s: %r", code, table.get(code))
        return 0.0


def download_proxy_ohlcv(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Daily OHLCV proxy for an MCX commodity symbol (``end`` exclusive, like yfinance).

    Returns an empty frame when the commodity has no global benchmark or either
    input series is empty; callers turn that into their usual no-data error.
    """
    # Lazy: stockstats_utils imports this module lazily as well.
    from ..stockstats_utils import yf_retry

    code = proxy_code(symbol)
    if code is None:
        raise ValueError(f"not an MCX proxy symbol: {symbol!r}")
    spec = COMMODITIES[code]
    empty = pd.DataFrame(columns=_OHLCV, index=pd.DatetimeIndex([], name="Date"))
    if spec.global_symbol is None:
        return empty

    kwargs = {
        "start": start, "end": end, "multi_level_index": False,
        "progress": False, "auto_adjust": True,
    }
    future = _daily(yf_retry(lambda: yf.download(spec.global_symbol, **kwargs)))
    fx = _daily(yf_retry(lambda: yf.download(_USDINR, **kwargs)))
    if future.empty or fx.empty or "Close" not in future or "Close" not in fx:
        return empty

    # Futures and FX follow different holiday calendars: carry the latest FX
    # close forward onto each futures session.
    fx_close = (
        pd.to_numeric(fx["Close"], errors="coerce")
        .reindex(future.index.union(fx.index))
        .sort_index()
        .ffill()
        .reindex(future.index)
    )
    multiplier = fx_close * spec.factor * (1.0 + _premium(code))

    out = pd.DataFrame(index=future.index)
    for column in ("Open", "High", "Low", "Close"):
        out[column] = (pd.to_numeric(future[column], errors="coerce") * multiplier).round(2)
    out["Volume"] = pd.to_numeric(future["Volume"], errors="coerce") if "Volume" in future else 0
    out = out.dropna(subset=["Close"])
    out.index.name = "Date"
    return out
