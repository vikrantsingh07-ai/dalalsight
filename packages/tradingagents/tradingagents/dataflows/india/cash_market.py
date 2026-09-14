"""Indian cash-market data from NSE: delivery %, corporate events, FII/DII flows, index valuation.

* Security-wise delivery (``sec_bhavdata_full``): traded vs deliverable quantity per
  session — India's standard gauge of genuine accumulation versus intraday churn.
* Corporate actions, board-meeting calendar and exchange announcements (NSE API).
* FII/DII provisional cash-market flows (NSE API, latest session only).
* Index close file (``ind_close_all``): index P/E, P/B and dividend yield history.

Dated files and dated records are filtered to the analysis date, so historical
runs only see what was public by then.
"""

from __future__ import annotations

import io
import logging
from datetime import date, datetime, timedelta

import pandas as pd

from ..errors import NoMarketDataError
from .instruments import INDICES, IndianInstrument, parse_indian_symbol
from .nse_client import (
    ExchangeDataUnavailableError,
    fetch_archive,
    invalidate_archive,
    nse_api_json,
    weekdays_back,
)

logger = logging.getLogger(__name__)

SECURITY_BHAVDATA_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{dmy}.csv"
INDEX_CLOSE_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{dmy}.csv"

_SECURITY_NUMERIC = (
    "PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "LAST_PRICE", "CLOSE_PRICE",
    "AVG_PRICE", "TTL_TRD_QNTY", "TURNOVER_LACS", "NO_OF_TRADES", "DELIV_QTY", "DELIV_PER",
)


def _as_date(value: str) -> date:
    return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()


def _dmy(day: date) -> str:
    return day.strftime("%d-%m-%Y")


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _fmt(value, spec: str = ",.2f") -> str:
    number = _num(value)
    return "n/a" if number is None else format(number, spec)


def _nse_date(value) -> date | None:
    for pattern in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M:%S"):
        try:
            return datetime.strptime(str(value).strip(), pattern).date()
        except (TypeError, ValueError):
            continue
    return None


def _company_instrument(symbol: str) -> tuple[IndianInstrument | None, str | None]:
    inst = parse_indian_symbol(symbol, india_mode=True)
    if inst is None:
        return None, f"'{symbol}' is not a recognised Indian instrument; use an NSE symbol such as RELIANCE."
    if inst.underlying_kind != "stock":
        return None, (
            f"{symbol} is a {inst.segment} instrument on {inst.underlying}; delivery and corporate-event "
            "data apply to NSE-listed companies only."
        )
    if inst.exchange != "NSE":
        return None, (
            f"{symbol} is a BSE scrip code; this data is keyed by NSE symbol, so use the NSE symbol "
            "(e.g. RELIANCE.NS)."
        )
    return inst, None


# ---------------------------------------------------------------------------
# Delivery percentage
# ---------------------------------------------------------------------------


def parse_security_bhavdata(raw: bytes) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(raw), dtype=str, skipinitialspace=True)
    frame.columns = [column.strip() for column in frame.columns]
    for column in frame.columns:
        frame[column] = frame[column].astype(str).str.strip()
    for column in _SECURITY_NUMERIC:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def load_security_bhavdata(day: date) -> pd.DataFrame | None:
    dmy = day.strftime("%d%m%Y")
    group, name = "nse_security_bhavdata", f"{dmy}.csv"
    raw = fetch_archive(SECURITY_BHAVDATA_URL.format(dmy=dmy), group=group, name=name, trade_day=day)
    if raw is None:
        return None
    try:
        return parse_security_bhavdata(raw)
    except (ValueError, KeyError, pd.errors.ParserError) as exc:
        logger.warning("Unreadable NSE security bhavdata for %s: %s", day, exc)
        invalidate_archive(group, name)
        return None


def delivery_analysis(symbol: str, curr_date: str, look_back_days: int = 10) -> str:
    """Delivery-percentage trend for an NSE stock over recent sessions."""
    inst, problem = _company_instrument(symbol)
    if problem:
        return problem
    wanted = max(3, min(int(look_back_days or 10), 20))
    rows = []
    files_without_symbol = 0
    for day in weekdays_back(_as_date(curr_date), max_days=wanted * 2 + 12):
        frame = load_security_bhavdata(day)
        if frame is None:
            continue
        match = frame[frame["SYMBOL"].str.upper() == inst.underlying]
        equity = match[match["SERIES"] == "EQ"]
        match = equity if not equity.empty else match
        if match.empty:
            files_without_symbol += 1
            if not rows and files_without_symbol >= 3:
                break  # symbol not traded on NSE; stop downloading files
            continue
        record = match.iloc[0]
        rows.append({
            "day": day,
            "series": record.get("SERIES"),
            "close": _num(record.get("CLOSE_PRICE")),
            "previous": _num(record.get("PREV_CLOSE")),
            "volume": _num(record.get("TTL_TRD_QNTY")),
            "delivered": _num(record.get("DELIV_QTY")),
            "delivery_pct": _num(record.get("DELIV_PER")),
            "turnover_lakh": _num(record.get("TURNOVER_LACS")),
        })
        if len(rows) >= wanted:
            break
    if not rows:
        raise NoMarketDataError(
            symbol, inst.underlying, f"not found in NSE security-wise delivery files on or before {curr_date}"
        )

    rows.reverse()
    for row in rows:
        row["change"] = (
            (row["close"] - row["previous"]) / row["previous"] * 100
            if row["close"] and row["previous"] else None
        )
    delivery_values = [r["delivery_pct"] for r in rows if r["delivery_pct"] is not None]
    volumes = [r["volume"] for r in rows if r["volume"]]
    average_delivery = sum(delivery_values) / len(delivery_values) if delivery_values else None
    average_volume = sum(volumes) / len(volumes) if volumes else None
    latest = rows[-1]
    high_delivery_up = sum(
        1 for r in rows
        if average_delivery and r["delivery_pct"] and r["change"] is not None
        and r["delivery_pct"] > average_delivery and r["change"] > 0
    )
    high_delivery_down = sum(
        1 for r in rows
        if average_delivery and r["delivery_pct"] and r["change"] is not None
        and r["delivery_pct"] > average_delivery and r["change"] < 0
    )

    lines = [
        f"# NSE delivery analysis: {inst.underlying} ({rows[0]['day'].isoformat()} → {latest['day'].isoformat()})",
        "",
        f"- Latest session {latest['day'].isoformat()}: close ₹{_fmt(latest['close'])} "
        f"({_fmt(latest['change'], '+.2f')}%), volume {_fmt(latest['volume'], ',.0f')} shares, delivery "
        f"{_fmt(latest['delivery_pct'], '.2f')}%",
        f"- Window average delivery {_fmt(average_delivery, '.2f')}%; latest volume is "
        f"{_fmt(latest['volume'] / average_volume if latest['volume'] and average_volume else None, '.2f')}× "
        "the window average",
        f"- Above-average-delivery sessions: {high_delivery_up} up days vs {high_delivery_down} down days",
        "",
        "| Date | Close (₹) | Chg % | Volume | Delivered qty | Delivery % | Turnover (₹ lakh) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['day'].isoformat()} | {_fmt(row['close'])} | {_fmt(row['change'], '+.2f')} | "
            f"{_fmt(row['volume'], ',.0f')} | {_fmt(row['delivered'], ',.0f')} | "
            f"{_fmt(row['delivery_pct'], '.2f')} | {_fmt(row['turnover_lakh'], ',.2f')} |"
        )
    lines += [
        "",
        "Notes: delivery % is the share of traded quantity settled into demat accounts rather than squared "
        "off intraday. Rising prices on above-average delivery suggest accumulation; falling prices on "
        "above-average delivery suggest distribution; low delivery marks speculative, intraday-driven moves.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Corporate actions, board meetings and announcements
# ---------------------------------------------------------------------------


def corporate_events(symbol: str, curr_date: str) -> str:
    """Corporate actions, results/board-meeting calendar and recent filings for an NSE stock."""
    inst, problem = _company_instrument(symbol)
    if problem:
        return problem
    as_of = _as_date(curr_date)
    # Upcoming events are only knowable for a live run; a historical run sees
    # what had already happened, so no post-decision information leaks in.
    live = as_of >= date.today()
    horizon = as_of + timedelta(days=120) if live else as_of
    sections: list[str] = []
    failures: list[str] = []

    try:
        actions = nse_api_json(
            "corporates-corporateActions",
            {"index": "equities", "symbol": inst.underlying,
             "from_date": _dmy(as_of - timedelta(days=730)), "to_date": _dmy(horizon)},
        ) or []
        kept = []
        for action in actions if isinstance(actions, list) else []:
            ex_date = _nse_date(action.get("exDate"))
            if ex_date is None or ex_date > horizon:
                continue
            kept.append((ex_date, str(action.get("subject") or "").strip()))
        kept.sort(reverse=True)
        body = "\n".join(
            f"| {d.isoformat()} | {'upcoming' if d > as_of else 'past'} | {subject} |" for d, subject in kept[:15]
        ) or "| — | — | No corporate actions in the window |"
        sections.append(
            "## Corporate actions (dividends, splits, bonus, rights)\n\n| Ex-date | Status | Action |\n|---|---|---|\n"
            + body
        )
    except (ExchangeDataUnavailableError, ValueError) as exc:
        failures.append(f"corporate actions ({exc})")

    try:
        calendar_rows = nse_api_json("event-calendar", {"index": "equities", "symbol": inst.underlying}) or []
        kept = []
        for event in calendar_rows if isinstance(calendar_rows, list) else []:
            event_date = _nse_date(event.get("date"))
            if event_date is None or event_date < as_of - timedelta(days=365) or event_date > horizon:
                continue
            description = " ".join(str(event.get("bm_desc") or "").split())
            if len(description) > 220:
                description = description[:220] + "…"
            kept.append((event_date, str(event.get("purpose") or "").strip(), description))
        kept.sort(reverse=True)
        body = "\n".join(
            f"| {d.isoformat()} | {'upcoming' if d > as_of else 'past'} | {purpose} | {desc} |"
            for d, purpose, desc in kept[:12]
        ) or "| — | — | — | No board meetings in the window |"
        sections.append(
            "## Board meetings / results calendar\n\n| Date | Status | Purpose | Details |\n|---|---|---|---|\n" + body
        )
    except (ExchangeDataUnavailableError, ValueError) as exc:
        failures.append(f"event calendar ({exc})")

    try:
        announcements = nse_api_json(
            "corporate-announcements",
            {"index": "equities", "symbol": inst.underlying,
             "from_date": _dmy(as_of - timedelta(days=30)), "to_date": _dmy(as_of)},
        ) or []
        kept = []
        for item in announcements if isinstance(announcements, list) else []:
            stamp = _nse_date(item.get("sort_date")) or _nse_date(str(item.get("an_dt", ""))[:11])
            if stamp is None or stamp > as_of:
                continue
            text = " ".join(str(item.get("attchmntText") or "").split())
            if len(text) > 240:
                text = text[:240] + "…"
            kept.append((str(item.get("sort_date") or stamp.isoformat()), str(item.get("desc") or "").strip(), text))
        kept.sort(reverse=True)
        body = "\n".join(f"- {stamp} — **{desc}**: {text}" for stamp, desc, text in kept[:12]) or (
            "- No exchange filings in the last 30 days."
        )
        sections.append(f"## Exchange filings, last 30 days to {as_of.isoformat()}\n\n{body}")
    except (ExchangeDataUnavailableError, ValueError) as exc:
        failures.append(f"announcements ({exc})")

    if not sections:
        raise ExchangeDataUnavailableError(f"NSE corporate data unavailable: {'; '.join(failures)}")
    header = f"# NSE corporate events: {inst.underlying} (as of {as_of.isoformat()})"
    if not live:
        header += "\n\nHistorical run: upcoming events announced after the analysis date are excluded."
    if failures:
        header += f"\n\nUnavailable sources: {'; '.join(failures)}."
    return header + "\n\n" + "\n\n".join(sections)


# ---------------------------------------------------------------------------
# FII / DII cash-market flows
# ---------------------------------------------------------------------------


def fii_dii_cash_flows(curr_date: str) -> str:
    """Latest provisional FII/FPI and DII cash-market buy/sell figures (₹ crore)."""
    as_of = _as_date(curr_date)
    data = nse_api_json("fiidiiTradeReact")
    rows = [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
    if not rows:
        raise NoMarketDataError("NSE FII/DII flows", None, "empty response")
    session = _nse_date(rows[0].get("date"))
    if session is None:
        raise NoMarketDataError("NSE FII/DII flows", None, "response carried no session date")
    if session > as_of:
        return (
            f"NSE publishes only the latest session's provisional FII/DII cash figures (currently "
            f"{session.isoformat()}), which is after the analysis date {as_of.isoformat()}. Historical "
            "figures are not available from this source, so leave FII/DII cash flows out rather than "
            "estimating them."
        )
    lines = [
        f"# FII/FPI and DII cash-market activity — {session.isoformat()} (provisional, ₹ crore)",
        "",
        "| Category | Buy | Sell | Net |",
        "|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('category', '?')} | {_fmt(row.get('buyValue'))} | {_fmt(row.get('sellValue'))} | "
            f"{_fmt(row.get('netValue'), '+,.2f')} |"
        )
    # State the flow arithmetic explicitly: agents previously misread these figures
    # (claiming DIIs absorbed "<70%" when they bought twice the FII selling).
    nets: dict[str, float] = {}
    for row in rows:
        category = str(row.get("category", "")).upper()
        value = _num(row.get("netValue"))
        if value is None:
            continue
        if "FII" in category or "FPI" in category:
            nets["FII"] = value
        elif "DII" in category:
            nets["DII"] = value
    fii, dii = nets.get("FII"), nets.get("DII")
    if fii is not None and dii is not None:
        lines.append(f"\nCombined FII/FPI + DII net: {_fmt(fii + dii, '+,.2f')} crore.")
        if fii < 0 < dii:
            lines.append(
                f"DII net buying ({_fmt(dii)} crore) equals {dii / -fii * 100:.0f}% of FII/FPI net selling "
                f"({_fmt(-fii)} crore): DIIs {'more than absorbed' if dii >= -fii else 'partly absorbed'} the foreign selling."
            )
        elif dii < 0 < fii:
            lines.append(
                f"FII/FPI net buying ({_fmt(fii)} crore) equals {fii / -dii * 100:.0f}% of DII net selling "
                f"({_fmt(-dii)} crore): FIIs {'more than absorbed' if fii >= -dii else 'partly absorbed'} the domestic selling."
            )
    if (as_of - session).days > 4:
        lines.append(f"\nThe latest published session ({session.isoformat()}) is several days before the analysis date.")
    lines.append(
        "\nNotes: provisional exchange figures for the cash segment only. Sustained FII/FPI selling pressures "
        "large caps and the rupee; DII (mutual fund, insurance) buying often absorbs it."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Index valuation (P/E, P/B, dividend yield)
# ---------------------------------------------------------------------------


def load_index_closes(day: date) -> pd.DataFrame | None:
    dmy = day.strftime("%d%m%Y")
    group, name = "nse_index_close", f"{dmy}.csv"
    raw = fetch_archive(INDEX_CLOSE_URL.format(dmy=dmy), group=group, name=name, trade_day=day)
    if raw is None:
        return None
    try:
        frame = pd.read_csv(io.BytesIO(raw), dtype=str)
    except (ValueError, pd.errors.ParserError) as exc:
        logger.warning("Unreadable NSE index close file for %s: %s", day, exc)
        invalidate_archive(group, name)
        return None
    frame.columns = [column.strip() for column in frame.columns]
    frame["Index Name"] = frame["Index Name"].astype(str).str.strip()
    return frame


def _index_session(target: date, index_name: str) -> tuple[date, pd.Series] | None:
    for day in weekdays_back(target, max_days=10):
        frame = load_index_closes(day)
        if frame is None:
            continue
        match = frame[frame["Index Name"].str.lower() == index_name.lower()]
        if not match.empty:
            return day, match.iloc[0]
    return None


def index_fundamentals(ticker: str, curr_date: str | None = None) -> str:
    """Valuation history (P/E, P/B, dividend yield) for an NSE index."""
    inst = parse_indian_symbol(ticker)
    if inst is None or inst.underlying_kind != "index":
        raise NoMarketDataError(ticker, None, "NSE index valuation applies to Indian indices only")
    spec = INDICES[inst.underlying]
    if spec.exchange != "NSE":
        raise NoMarketDataError(ticker, spec.yahoo, "valuation history is published for NSE indices only")
    as_of = _as_date(curr_date) if curr_date else date.today()

    points = [("Latest", 0), ("~1 month earlier", 30), ("~3 months earlier", 91),
              ("~6 months earlier", 182), ("~1 year earlier", 365), ("~3 years earlier", 1095)]
    rows = []
    for label, days in points:
        found = _index_session(as_of - timedelta(days=days), spec.name)
        if found:
            day, record = found
            rows.append((label, day, record))
    if not rows:
        raise NoMarketDataError(
            ticker, spec.yahoo, f"'{spec.name}' not found in NSE index close files on or before {as_of}"
        )

    lines = [
        f"# Index valuation: {spec.name} ({inst.underlying}) — NSE index close files",
        "",
        "| Point | Date | Close | Change % | P/E | P/B | Dividend yield % |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for label, day, record in rows:
        lines.append(
            f"| {label} | {day.isoformat()} | {_fmt(record.get('Closing Index Value'))} | "
            f"{_fmt(record.get('Change(%)'), '+.2f')} | {_fmt(record.get('P/E'))} | "
            f"{_fmt(record.get('P/B'))} | {_fmt(record.get('Div Yield'))} |"
        )
    latest_pe = _num(rows[0][2].get("P/E"))
    year_ago = next((record for label, _, record in rows if label == "~1 year earlier"), None)
    if latest_pe and year_ago is not None and _num(year_ago.get("P/E")):
        lines.append(
            f"\nP/E is {latest_pe:.2f} versus {_num(year_ago.get('P/E')):.2f} a year earlier "
            f"({(latest_pe / _num(year_ago.get('P/E')) - 1) * 100:+.1f}%)."
        )
    lines.append(
        "\nNotes: an index is not a company, so balance-sheet tools do not apply; valuation relative to its "
        "own history (P/E, P/B, dividend yield), earnings growth of its heavyweights and flows matter instead."
    )
    return "\n".join(lines)


__all__ = [
    "corporate_events",
    "delivery_analysis",
    "fii_dii_cash_flows",
    "index_fundamentals",
    "parse_security_bhavdata",
]
