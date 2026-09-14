"""Daily history for NSE indices from NSE's index-history API.

Yahoo's feeds for some NSE indices are stale (NIFTY Financial Services stopped
updating on 2026-07-17) or nearly empty (NIFTY Midcap Select returns one row),
which left price tools with no usable history. NSE publishes official daily
OHLC for every NSE index. The API rejects spans over a year and returns at most
70 sessions per request, so history is fetched in 90-day windows; windows that
ended before yesterday are immutable and cached on disk.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta

import pandas as pd

from .instruments import INDICES
from .nse_client import _cache_path, nse_api_json

logger = logging.getLogger(__name__)

_WINDOW_DAYS = 90
_STALE_DAYS = 10

# Yahoo symbol -> NSE index name for NSE-published indices (India VIX has its own series).
NSE_INDEX_BY_YAHOO = {
    spec.yahoo: spec.name.upper()
    for key, spec in INDICES.items()
    if spec.exchange == "NSE" and key != "INDIAVIX"
}


def _as_date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _frame_dates(frame: pd.DataFrame | None) -> pd.Series:
    if frame is None or len(frame) == 0:
        return pd.Series(dtype="datetime64[ns, UTC]")
    if "Date" in frame.columns:
        dates = pd.to_datetime(frame["Date"], errors="coerce", utc=True)
    else:
        dates = pd.Series(pd.to_datetime(frame.index, errors="coerce", utc=True))
    return dates.dropna()


def needs_nse_index_fallback(canonical: str, frame: pd.DataFrame | None, start, end) -> bool:
    """True for an NSE index whose frame is empty, stale, or far shorter than the window."""
    if canonical not in NSE_INDEX_BY_YAHOO:
        return False
    dates = _frame_dates(frame)
    if dates.empty:
        return True
    start_d, end_d = _as_date(start), _as_date(end)
    if (end_d - dates.max().date()).days > _STALE_DAYS:
        return True
    expected_sessions = (end_d - start_d).days * 5 / 7 * 0.9
    return len(dates) < 0.5 * expected_sessions


def _fetch_window(index_name: str, start: date, end: date) -> list[dict]:
    slug = "".join(ch if ch.isalnum() else "_" for ch in index_name)
    path = _cache_path("nse_index_history", f"{slug}_{start:%Y%m%d}_{end:%Y%m%d}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    payload = nse_api_json(
        "historicalOR/indicesHistory",
        {"indexType": index_name, "from": start.strftime("%d-%m-%Y"), "to": end.strftime("%d-%m-%Y")},
    )
    rows = payload if isinstance(payload, list) else (payload or {}).get("data", [])
    rows = rows if isinstance(rows, list) else []
    if end < date.today() - timedelta(days=1):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rows, fh)
    return rows


def fetch_nse_index_history(index_name: str, start, end) -> pd.DataFrame:
    """Daily OHLC (+ traded quantity as Volume) indexed by naive ``Date``."""
    start_d, end_d = _as_date(start), _as_date(end)
    records = []
    cursor = start_d
    while cursor <= end_d:
        window_end = min(end_d, cursor + timedelta(days=_WINDOW_DAYS - 1))
        for row in _fetch_window(index_name, cursor, window_end):
            try:
                day = datetime.strptime(str(row["EOD_TIMESTAMP"]).title(), "%d-%b-%Y")
                records.append({
                    "Date": day,
                    "Open": float(row["EOD_OPEN_INDEX_VAL"]),
                    "High": float(row["EOD_HIGH_INDEX_VAL"]),
                    "Low": float(row["EOD_LOW_INDEX_VAL"]),
                    "Close": float(row["EOD_CLOSE_INDEX_VAL"]),
                    "Volume": float(row.get("HIT_TRADED_QTY") or 0.0),
                })
            except (KeyError, TypeError, ValueError):
                continue
        cursor = window_end + timedelta(days=1)
    if not records:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"], index=pd.DatetimeIndex([], name="Date"))
    frame = pd.DataFrame(records).drop_duplicates("Date").sort_values("Date").set_index("Date")
    return frame[(frame.index.date >= start_d) & (frame.index.date <= end_d)]


def nse_index_history_frame(canonical: str, start, end) -> pd.DataFrame | None:
    """NSE history for a Yahoo index symbol, or None when not applicable or unavailable."""
    index_name = NSE_INDEX_BY_YAHOO.get(canonical)
    if index_name is None:
        return None
    try:
        frame = fetch_nse_index_history(index_name, start, end)
    except Exception as exc:  # noqa: BLE001 — fallback source; the caller keeps its own error path
        logger.warning("NSE index history unavailable for %s: %s", index_name, exc)
        return None
    return frame if not frame.empty else None
