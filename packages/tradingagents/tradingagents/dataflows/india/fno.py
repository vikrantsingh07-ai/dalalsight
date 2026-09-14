"""Indian equity-derivatives (F&O) analytics from official end-of-day exchange files.

Sources (no API key; access and caching live in ``nse_client``):

* NSE / BSE UDiFF F&O bhavcopy: every futures and options contract's close,
  settlement, underlying price, open interest, change in OI, volume and lot size
  for a session. It drives futures basis, OI build-up and rollover, and the
  option chain (PCR, max pain, OI walls, implied move, IV).
* NSE participant-wise open interest: FII / DII / Pro / Client positioning.
* India VIX daily closes (Yahoo ``^INDIAVIX``).

Every report is built only from files dated on or before the analysis date, so
historical runs never see the future. The bhavcopy publishes open interest in
units (shares / index units); it is converted to contracts by dividing by the
lot size. Traded volume is already published in contracts.
"""

from __future__ import annotations

import calendar
import io
import logging
import zipfile
from datetime import date, datetime
from math import erf, exp, log, pi, sqrt

import numpy as np
import pandas as pd

from ..config import get_config
from ..errors import NoMarketDataError
from .instruments import (
    COMMODITY,
    CURRENCY,
    FUTURES,
    INDEX,
    INDICES,
    OPTIONS,
    IndianInstrument,
    parse_indian_symbol,
)
from .nse_client import fetch_archive, invalidate_archive, weekdays_back

logger = logging.getLogger(__name__)

NSE_FO_BHAVCOPY_URL = (
    "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"
)
BSE_FO_BHAVCOPY_URL = (
    "https://www.bseindia.com/download/Bhavcopy/Derivative/BhavCopy_BSE_FO_0_0_0_{ymd}_F_0000.CSV"
)
PARTICIPANT_OI_URL = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{dmy}.csv"

_FUTURE_TYPES = frozenset({"IDF", "STF"})
_OPTION_TYPES = frozenset({"IDO", "STO"})
_BHAVCOPY_COLUMNS = frozenset({
    "TradDt", "FinInstrmTp", "TckrSymb", "XpryDt", "StrkPric", "OptnTp", "FinInstrmNm",
    "ClsPric", "LastPric", "PrvsClsgPric", "UndrlygPric", "SttlmPric", "OpnIntrst",
    "ChngInOpnIntrst", "TtlTradgVol", "NewBrdLotQty",
})
_NUMERIC_COLUMNS = (
    "StrkPric", "ClsPric", "LastPric", "PrvsClsgPric", "UndrlygPric", "SttlmPric",
    "OpnIntrst", "ChngInOpnIntrst", "TtlTradgVol", "NewBrdLotQty",
)
_MAX_FUTURES_SESSIONS = 20
_PARTICIPANTS = ("FII", "DII", "Pro", "Client")


# ---------------------------------------------------------------------------
# Small numeric / formatting helpers
# ---------------------------------------------------------------------------


def _as_date(value: str) -> date:
    return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number  # NaN -> None


def _fmt(value, spec: str = ",.2f") -> str:
    number = _num(value)
    return "n/a" if number is None else format(number, spec)


def _signed_pct(value) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{number:+.2f}%"


def _strike(value) -> str:
    number = _num(value)
    if number is None:
        return "n/a"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _risk_free_rate() -> float:
    try:
        return float(get_config().get("india_risk_free_rate", 0.065))
    except (TypeError, ValueError):
        return 0.065


# ---------------------------------------------------------------------------
# Black-Scholes implied volatility and Greeks
# ---------------------------------------------------------------------------


def _cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


def bs_price(spot: float, strike: float, years: float, rate: float, vol: float, option_type: str) -> float:
    """European Black-Scholes price for a CE (call) or PE (put)."""
    discounted_strike = strike * exp(-rate * max(years, 0.0))
    if years <= 0 or vol <= 0:
        if option_type == "CE":
            return max(0.0, spot - discounted_strike)
        return max(0.0, discounted_strike - spot)
    spread = vol * sqrt(years)
    d1 = (log(spot / strike) + (rate + 0.5 * vol * vol) * years) / spread
    d2 = d1 - spread
    if option_type == "CE":
        return spot * _cdf(d1) - discounted_strike * _cdf(d2)
    return discounted_strike * _cdf(-d2) - spot * _cdf(-d1)


def implied_volatility(
    price, spot, strike, years, rate: float, option_type: str,
    *, low: float = 1e-4, high: float = 5.0, tolerance: float = 1e-5, max_iter: int = 100,
) -> float | None:
    """Annualised implied volatility by bisection, or None when no volatility fits the price."""
    values = [_num(v) for v in (price, spot, strike, years)]
    if any(v is None or v <= 0 for v in values):
        return None
    price, spot, strike, years = values
    if bs_price(spot, strike, years, rate, low, option_type) > price + tolerance:
        return None  # below intrinsic value: stale or arbitrage print
    if bs_price(spot, strike, years, rate, high, option_type) < price:
        return None
    for _ in range(max_iter):
        mid = 0.5 * (low + high)
        if bs_price(spot, strike, years, rate, mid, option_type) > price:
            high = mid
        else:
            low = mid
        if high - low < tolerance:
            break
    return 0.5 * (low + high)


def option_greeks(spot: float, strike: float, years: float, rate: float, vol: float, option_type: str) -> dict:
    """Delta, gamma, theta per calendar day and vega per volatility point."""
    spread = vol * sqrt(years)
    d1 = (log(spot / strike) + (rate + 0.5 * vol * vol) * years) / spread
    d2 = d1 - spread
    discounted_strike = strike * exp(-rate * years)
    density = _pdf(d1)
    decay = -(spot * density * vol) / (2.0 * sqrt(years))
    if option_type == "CE":
        delta = _cdf(d1)
        theta = decay - rate * discounted_strike * _cdf(d2)
    else:
        delta = _cdf(d1) - 1.0
        theta = decay + rate * discounted_strike * _cdf(-d2)
    return {
        "delta": delta,
        "gamma": density / (spot * spread),
        "theta_per_day": theta / 365.0,
        "vega_per_vol_point": spot * density * sqrt(years) / 100.0,
    }


# ---------------------------------------------------------------------------
# Bhavcopy loading
# ---------------------------------------------------------------------------


def parse_fo_bhavcopy(raw: bytes) -> pd.DataFrame:
    """Parse a UDiFF F&O bhavcopy (zipped NSE file or plain BSE CSV)."""
    data = raw
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            data = archive.read(archive.namelist()[0])
    frame = pd.read_csv(
        io.BytesIO(data), dtype=str, usecols=lambda column: column.strip() in _BHAVCOPY_COLUMNS
    )
    frame.columns = [column.strip() for column in frame.columns]
    for column in _NUMERIC_COLUMNS:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in ("TckrSymb", "FinInstrmTp", "OptnTp", "FinInstrmNm"):
        if column in frame:
            frame[column] = frame[column].fillna("").astype(str).str.strip().str.upper()
    frame["XpryDt"] = pd.to_datetime(frame["XpryDt"], errors="coerce").dt.date
    return frame.dropna(subset=["XpryDt"])


def load_fo_bhavcopy(day: date, exchange: str = "NSE") -> pd.DataFrame | None:
    """One session's F&O bhavcopy, or None when the exchange published none that day."""
    ymd = day.strftime("%Y%m%d")
    if exchange == "BSE":
        group, name = "bse_fo_bhavcopy", f"{ymd}.csv"
        raw = fetch_archive(
            BSE_FO_BHAVCOPY_URL.format(ymd=ymd), group=group, name=name, trade_day=day, source="bse"
        )
    else:
        group, name = "nse_fo_bhavcopy", f"{ymd}.csv.zip"
        raw = fetch_archive(NSE_FO_BHAVCOPY_URL.format(ymd=ymd), group=group, name=name, trade_day=day)
    if raw is None:
        return None
    try:
        return parse_fo_bhavcopy(raw)
    except (ValueError, KeyError, zipfile.BadZipFile, pd.errors.ParserError) as exc:
        logger.warning("Unreadable %s F&O bhavcopy for %s: %s", exchange, day, exc)
        invalidate_archive(group, name)
        return None


def recent_fo_sessions(as_of: date, sessions: int, exchange: str = "NSE") -> list[tuple[date, pd.DataFrame]]:
    """Up to ``sessions`` bhavcopies dated on or before ``as_of``, newest first."""
    found: list[tuple[date, pd.DataFrame]] = []
    for day in weekdays_back(as_of, max_days=sessions * 2 + 12):
        frame = load_fo_bhavcopy(day, exchange)
        if frame is not None and not frame.empty:
            found.append((day, frame))
            if len(found) >= sessions:
                break
    return found


def _select(frame: pd.DataFrame, inst: IndianInstrument, types: frozenset) -> pd.DataFrame:
    return frame[(frame["TckrSymb"] == inst.underlying) & frame["FinInstrmTp"].isin(types)]


def _lot_size(rows: pd.DataFrame) -> int | None:
    lots = rows["NewBrdLotQty"].dropna()
    lots = lots[lots > 0]
    return int(lots.max()) if not lots.empty else None


def _contracts(rows: pd.DataFrame, column: str) -> pd.Series:
    """Convert a unit-denominated bhavcopy column to contracts using each row's lot size."""
    lots = rows["NewBrdLotQty"].where(rows["NewBrdLotQty"] > 0)
    return rows[column] / lots.fillna(1.0)


def _pick_expiry(expiries, inst: IndianInstrument, as_of: date) -> tuple[date | None, str | None]:
    """The expiry an instrument refers to, or (None, reason)."""
    listed = sorted(set(expiries))
    if inst.expiry_day:
        target = date(inst.expiry_year, inst.expiry_month, inst.expiry_day)
        if target in listed:
            return target, None
        return None, f"The {target.isoformat()} expiry is not listed in the {as_of.isoformat()} bhavcopy (expired or not yet listed)"
    if inst.expiry_month:
        in_month = [e for e in listed if (e.year, e.month) == (inst.expiry_year, inst.expiry_month)]
        if in_month:
            # The monthly contract is the last expiry of the month.
            return max(in_month), None
        label = f"{calendar.month_abbr[inst.expiry_month]} {inst.expiry_year}"
        return None, f"No {label} contract is listed in the {as_of.isoformat()} bhavcopy (expired or not yet listed)"
    upcoming = [e for e in listed if e >= as_of]
    if upcoming:
        return upcoming[0], None
    return (listed[-1] if listed else None), None


def _fno_instrument(symbol: str) -> tuple[IndianInstrument | None, str | None]:
    """Resolve a symbol for the F&O tools, or return an explanation why they do not apply."""
    inst = parse_indian_symbol(symbol, india_mode=True)
    if inst is None:
        return None, (
            f"'{symbol}' is not a recognised Indian instrument. Use an NSE symbol (e.g. RELIANCE), "
            "an index (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX) or a contract such as NIFTY26SEPFUT."
        )
    if inst.supports_exchange_derivatives:
        return inst, None
    if inst.segment == COMMODITY:
        return None, (
            f"{symbol} is an MCX commodity. MCX open interest and option-chain data are not available "
            "from a free source, so there is no derivatives positioning data: analyse the price proxy, "
            "news and global benchmark trends instead, and do not invent open-interest figures."
        )
    if inst.segment == CURRENCY:
        return None, (
            f"{symbol} is an NSE currency pair. Currency-derivatives open interest is not covered by "
            "these tools: rely on the spot rate, RBI policy, crude oil and FPI-flow context instead."
        )
    if inst.segment == INDEX:
        return None, f"{inst.name or symbol} has no exchange-traded futures or options."
    return None, (
        f"{symbol} is a BSE scrip code. Exchange F&O data is keyed by NSE symbol: use the NSE symbol "
        "(e.g. RELIANCE.NS) to check futures and options positioning."
    )


def resolve_contract(symbol: str, curr_date: str) -> dict | None:
    """Best-effort expiry and lot size for a futures/options symbol (fail-open, may hit the network)."""
    inst = parse_indian_symbol(symbol)
    if inst is None or inst.segment not in (FUTURES, OPTIONS):
        return None
    try:
        sessions = recent_fo_sessions(_as_date(curr_date), 1, inst.fno_exchange)
    except Exception as exc:  # noqa: BLE001 — context enrichment must never block a run
        logger.debug("Could not resolve contract for %s: %s", symbol, exc)
        return None
    if not sessions:
        return None
    day, frame = sessions[0]
    rows = _select(frame, inst, _FUTURE_TYPES if inst.segment == FUTURES else _OPTION_TYPES)
    if rows.empty:
        return None
    expiry, _ = _pick_expiry(rows["XpryDt"], inst, day)
    if expiry is None:
        return None
    return {
        "as_of": day.isoformat(),
        "expiry": expiry.isoformat(),
        "days_to_expiry": (expiry - day).days,
        "lot_size": _lot_size(rows[rows["XpryDt"] == expiry]),
    }


# ---------------------------------------------------------------------------
# Futures: basis, open-interest build-up, rollover
# ---------------------------------------------------------------------------


def classify_buildup(price_change, oi_change) -> str:
    """Standard price / open-interest build-up classification."""
    price_change, oi_change = _num(price_change), _num(oi_change)
    if price_change is None or oi_change is None or oi_change == 0:
        return "No clear build-up"
    if oi_change > 0:
        return "Long build-up" if price_change >= 0 else "Short build-up"
    return "Short covering" if price_change >= 0 else "Long unwinding"


def _near_month(day: date, frame: pd.DataFrame, inst: IndianInstrument) -> dict | None:
    futures = _select(frame, inst, _FUTURE_TYPES)
    futures = futures[futures["XpryDt"] >= day].sort_values("XpryDt")
    if futures.empty:
        return None
    near = futures.iloc[0]
    close = _num(near["ClsPric"]) or _num(near["SttlmPric"])
    previous = _num(near["PrvsClsgPric"])
    spot = _num(near["UndrlygPric"])
    oi_units = _num(futures["OpnIntrst"].sum()) or 0.0
    change_units = _num(futures["ChngInOpnIntrst"].sum()) or 0.0
    near_units = _num(near["OpnIntrst"]) or 0.0
    price_change = (close - previous) / previous * 100 if close and previous else None
    basis = close - spot if close and spot else None
    basis_pct = basis / spot * 100 if basis is not None else None
    days_left = (near["XpryDt"] - day).days
    prior_units = oi_units - change_units
    return {
        "day": day,
        "expiry": near["XpryDt"],
        "days_left": days_left,
        "close": close,
        "price_change": price_change,
        "spot": spot,
        "basis": basis,
        "basis_pct": basis_pct,
        "carry": basis_pct * 365 / days_left if basis_pct is not None and days_left > 0 else None,
        "oi": _num(_contracts(futures, "OpnIntrst").sum()),
        "oi_change": _num(_contracts(futures, "ChngInOpnIntrst").sum()),
        "oi_change_pct": change_units / prior_units * 100 if prior_units > 0 else None,
        "volume": _num(futures["TtlTradgVol"].sum()),
        "rollover": (oi_units - near_units) / oi_units * 100 if oi_units > 0 else None,
        "buildup": classify_buildup(price_change, change_units),
    }


def futures_analysis(symbol: str, curr_date: str, look_back_days: int = 10) -> str:
    """Futures positioning report from the last ``look_back_days`` F&O bhavcopies."""
    inst, problem = _fno_instrument(symbol)
    if problem:
        return problem
    exchange = inst.fno_exchange
    wanted = max(2, min(int(look_back_days or 10), _MAX_FUTURES_SESSIONS))
    sessions = recent_fo_sessions(_as_date(curr_date), wanted, exchange)
    if not sessions:
        raise NoMarketDataError(
            symbol, inst.underlying, f"no {exchange} F&O bhavcopy found on or before {curr_date}"
        )

    latest_day, latest_frame = sessions[0]
    title = f"# Futures positioning: {inst.underlying} ({exchange} F&O, EOD bhavcopy {latest_day.isoformat()})"
    latest_futures = _select(latest_frame, inst, _FUTURE_TYPES).sort_values("XpryDt")
    if latest_futures.empty:
        return (
            f"{title}\n\n{inst.underlying} has no futures contracts in the {exchange} F&O bhavcopy "
            f"for {latest_day.isoformat()}: it is not in the derivatives segment (cash market only), "
            "so there is no futures positioning to analyse."
        )

    history = [
        row for row in (_near_month(day, frame, inst) for day, frame in reversed(sessions)) if row
    ]
    if not history:
        raise NoMarketDataError(symbol, inst.underlying, "no live futures contract in the bhavcopy window")
    last, first = history[-1], history[0]

    streak = 0
    for row in reversed(history):
        if row["buildup"] != last["buildup"]:
            break
        streak += 1

    lines = [title, ""]
    lines.append(
        f"Lot size: {_lot_size(latest_futures) or 'n/a'} units | Near-month expiry: "
        f"{last['expiry'].isoformat()} ({last['days_left']} days) | "
        f"Listed expiries: {', '.join(e.isoformat() for e in sorted(set(latest_futures['XpryDt'])))}"
    )
    lines += ["", "## Latest session"]
    lines.append(
        f"- Near-month future {_fmt(last['close'])} ({_signed_pct(last['price_change'])}); underlying "
        f"{_fmt(last['spot'])}; basis {_fmt(last['basis'], '+,.2f')} ({_signed_pct(last['basis_pct'])}), "
        f"≈ {_signed_pct(last['carry'])} annualised cost of carry"
    )
    lines.append(
        f"- Open interest, all expiries: {_fmt(last['oi'], ',.0f')} contracts "
        f"({_fmt(last['oi_change'], '+,.0f')}, {_signed_pct(last['oi_change_pct'])}) → "
        f"**{last['buildup']}** ({streak} consecutive session{'s' if streak != 1 else ''})"
    )
    lines.append(f"- Share of open interest already in later expiries (rollover): {_fmt(last['rollover'], '.1f')}%")

    if len(history) > 1 and first["spot"] and last["spot"] and first["oi"]:
        spot_move = (last["spot"] - first["spot"]) / first["spot"] * 100
        oi_move = (last["oi"] - first["oi"]) / first["oi"] * 100
        lines.append(
            f"- Window {first['day'].isoformat()} → {last['day'].isoformat()}: underlying "
            f"{_signed_pct(spot_move)}, futures OI {_signed_pct(oi_move)} → "
            f"{classify_buildup(spot_move, oi_move)} over the window"
        )

    if inst.segment == FUTURES and inst.expiry_month:
        expiry, note = _pick_expiry(latest_futures["XpryDt"], inst, latest_day)
        lines += ["", f"## Requested contract {inst.symbol}"]
        if expiry is None:
            lines.append(f"- {note}.")
        else:
            row = latest_futures[latest_futures["XpryDt"] == expiry].iloc[0]
            close = _num(row["ClsPric"]) or _num(row["SttlmPric"])
            spot = _num(row["UndrlygPric"])
            lot = _num(row["NewBrdLotQty"])
            lines.append(
                f"- Expiry {expiry.isoformat()} ({(expiry - latest_day).days} days), close {_fmt(close)}, "
                f"basis {_fmt(close - spot if close and spot else None, '+,.2f')}, OI "
                f"{_fmt(_num(row['OpnIntrst']) / lot if lot else None, ',.0f')} contracts, "
                f"lot {int(lot) if lot else 'n/a'} units, contract value ≈ ₹{_fmt(close * lot if close and lot else None, ',.0f')}"
            )

    lines += [
        "",
        f"## Expiry ladder ({latest_day.isoformat()})",
        "",
        "| Expiry | Days | Close | Chg % | Basis | Basis % | OI (contracts) | ΔOI (contracts) | Volume (contracts) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    ladder = latest_futures.assign(
        oi_contracts=_contracts(latest_futures, "OpnIntrst"),
        oi_change_contracts=_contracts(latest_futures, "ChngInOpnIntrst"),
    )
    for _, row in ladder.iterrows():
        close = _num(row["ClsPric"]) or _num(row["SttlmPric"])
        previous = _num(row["PrvsClsgPric"])
        spot = _num(row["UndrlygPric"])
        basis = close - spot if close and spot else None
        lines.append(
            f"| {row['XpryDt'].isoformat()} | {(row['XpryDt'] - latest_day).days} | {_fmt(close)} | "
            f"{_signed_pct((close - previous) / previous * 100 if close and previous else None)} | "
            f"{_fmt(basis, '+,.2f')} | {_signed_pct(basis / spot * 100 if basis is not None else None)} | "
            f"{_fmt(row['oi_contracts'], ',.0f')} | {_fmt(row['oi_change_contracts'], '+,.0f')} | "
            f"{_fmt(row['TtlTradgVol'], ',.0f')} |"
        )

    lines += [
        "",
        "## Session history (near-month contract; OI across all expiries)",
        "",
        "| Date | Expiry | Future | Chg % | Underlying | Basis % | OI (contracts) | ΔOI % | Build-up | Rollover % |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---:|",
    ]
    for row in history:
        lines.append(
            f"| {row['day'].isoformat()} | {row['expiry'].isoformat()} | {_fmt(row['close'])} | "
            f"{_signed_pct(row['price_change'])} | {_fmt(row['spot'])} | {_signed_pct(row['basis_pct'])} | "
            f"{_fmt(row['oi'], ',.0f')} | {_signed_pct(row['oi_change_pct'])} | {row['buildup']} | "
            f"{_fmt(row['rollover'], '.1f')} |"
        )
    lines += [
        "",
        "Notes: open interest is converted from exchange units to contracts (units ÷ lot size). "
        "Build-up: price↑ & OI↑ = long build-up, price↓ & OI↑ = short build-up, price↑ & OI↓ = short "
        "covering, price↓ & OI↓ = long unwinding. Rollover is most informative in the final week "
        "before the near-month expiry.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Options: chain metrics
# ---------------------------------------------------------------------------


def build_option_chain(rows: pd.DataFrame) -> pd.DataFrame:
    """Strike-indexed CE/PE chain (OI and ΔOI in contracts) for one expiry."""
    priced = rows.assign(
        oi=_contracts(rows, "OpnIntrst"),
        oi_change=_contracts(rows, "ChngInOpnIntrst"),
        premium=rows["ClsPric"].where(rows["ClsPric"] > 0, rows["SttlmPric"]),
    )
    sides = []
    for side in ("CE", "PE"):
        prefix = side.lower()
        grouped = priced[priced["OptnTp"] == side].groupby("StrkPric").agg(
            **{
                f"{prefix}_oi": ("oi", "sum"),
                f"{prefix}_chg": ("oi_change", "sum"),
                f"{prefix}_vol": ("TtlTradgVol", "sum"),
                f"{prefix}_px": ("premium", "last"),
            }
        )
        sides.append(grouped)
    chain = sides[0].join(sides[1], how="outer").sort_index()
    for column in ("ce_oi", "ce_chg", "ce_vol", "pe_oi", "pe_chg", "pe_vol"):
        chain[column] = chain[column].fillna(0.0)
    chain.index.name = "strike"
    return chain


def max_pain_strike(chain: pd.DataFrame) -> float | None:
    """Expiry price at which option holders' total intrinsic payout is smallest."""
    if chain.empty:
        return None
    strikes = chain.index.to_numpy(dtype=float)
    call_oi = chain["ce_oi"].to_numpy(dtype=float)
    put_oi = chain["pe_oi"].to_numpy(dtype=float)
    payouts = [
        float((call_oi * np.clip(settle - strikes, 0, None)).sum()
              + (put_oi * np.clip(strikes - settle, 0, None)).sum())
        for settle in strikes
    ]
    return float(strikes[int(np.argmin(payouts))])


def chain_metrics(chain: pd.DataFrame, spot, days_to_expiry: int, rate: float) -> dict:
    """PCRs, max pain, ATM strike, straddle-implied move and ATM IV for one expiry."""
    spot = _num(spot)
    call_oi, put_oi = chain["ce_oi"].sum(), chain["pe_oi"].sum()
    call_vol, put_vol = chain["ce_vol"].sum(), chain["pe_vol"].sum()
    call_chg, put_chg = chain["ce_chg"].sum(), chain["pe_chg"].sum()
    metrics = {
        "call_oi": call_oi,
        "put_oi": put_oi,
        "pcr_oi": put_oi / call_oi if call_oi > 0 else None,
        "pcr_volume": put_vol / call_vol if call_vol > 0 else None,
        "call_oi_change": call_chg,
        "put_oi_change": put_chg,
        "max_pain": max_pain_strike(chain),
        "atm": None,
        "straddle": None,
        "implied_move_pct": None,
        "atm_iv": None,
    }
    if spot is None or chain.empty:
        return metrics
    strikes = chain.index.to_numpy(dtype=float)
    atm = float(strikes[int(np.argmin(np.abs(strikes - spot)))])
    metrics["atm"] = atm
    call_px, put_px = _num(chain.at[atm, "ce_px"]), _num(chain.at[atm, "pe_px"])
    if call_px and put_px:
        metrics["straddle"] = call_px + put_px
        metrics["implied_move_pct"] = (call_px + put_px) / spot * 100
    if days_to_expiry > 0:
        years = days_to_expiry / 365
        ivs = [
            iv for iv in (
                implied_volatility(call_px, spot, atm, years, rate, "CE"),
                implied_volatility(put_px, spot, atm, years, rate, "PE"),
            ) if iv is not None
        ]
        if ivs:
            metrics["atm_iv"] = sum(ivs) / len(ivs)
    return metrics


def _strike_list(frame: pd.DataFrame, column: str) -> str:
    if frame.empty:
        return "none"
    return ", ".join(f"{_strike(strike)} ({_fmt(value, '+,.0f' if 'chg' in column else ',.0f')})"
                     for strike, value in frame[column].items())


def _contract_section(chain, inst, spot, days_to_expiry, rate, lot) -> list[str]:
    lines = ["", f"## Requested contract {inst.symbol}"]
    side = inst.option_type.lower()
    strike = float(inst.strike)
    if strike not in chain.index or _num(chain.at[strike, f"{side}_px"]) is None:
        nearby = chain.index.to_numpy(dtype=float)
        closest = sorted(nearby, key=lambda k: abs(k - strike))[:5]
        lines.append(
            f"- Strike {_strike(strike)} {inst.option_type} is not listed for this expiry. Nearest listed "
            f"strikes: {', '.join(_strike(k) for k in sorted(closest))}."
        )
        return lines
    premium = _num(chain.at[strike, f"{side}_px"])
    oi = _num(chain.at[strike, f"{side}_oi"])
    oi_change = _num(chain.at[strike, f"{side}_chg"])
    volume = _num(chain.at[strike, f"{side}_vol"])
    spot = _num(spot)
    is_call = inst.option_type == "CE"
    intrinsic = max(0.0, (spot - strike) if is_call else (strike - spot)) if spot else None
    breakeven = strike + premium if is_call else strike - premium
    lines.append(
        f"- Premium {_fmt(premium)} (OI {_fmt(oi, ',.0f')} contracts, ΔOI {_fmt(oi_change, '+,.0f')}, "
        f"volume {_fmt(volume, ',.0f')} contracts)"
    )
    if spot:
        moneyness = "in the money" if intrinsic and intrinsic > 0 else "out of the money"
        if abs(spot - strike) / spot < 0.005:
            moneyness = "at the money"
        lines.append(
            f"- Underlying {_fmt(spot)} → {moneyness}; intrinsic {_fmt(intrinsic)}, time value "
            f"{_fmt(premium - intrinsic if intrinsic is not None else None)}"
        )
        lines.append(
            f"- Breakeven at expiry {_fmt(breakeven)} ({_signed_pct((breakeven - spot) / spot * 100)} from spot)"
        )
    if lot:
        lines.append(f"- Lot size {lot} units → premium per lot ≈ ₹{_fmt(premium * lot, ',.0f')} (maximum loss for a buyer)")
    if days_to_expiry > 0 and spot:
        years = days_to_expiry / 365
        iv = implied_volatility(premium, spot, strike, years, rate, inst.option_type)
        if iv is not None:
            greeks = option_greeks(spot, strike, years, rate, iv, inst.option_type)
            lines.append(
                f"- Implied volatility {iv * 100:.1f}% | delta {greeks['delta']:+.3f} | gamma "
                f"{greeks['gamma']:.5f} | theta {greeks['theta_per_day']:+.2f} per day | vega "
                f"{greeks['vega_per_vol_point']:.2f} per vol point (Black-Scholes, r={rate:.2%})"
            )
        else:
            lines.append("- Implied volatility could not be solved from this premium (illiquid or stale print).")
    else:
        lines.append("- The contract expires today; Greeks are not meaningful.")
    return lines


def option_chain_analysis(symbol: str, curr_date: str, strikes_around_atm: int = 8) -> str:
    """Option-chain report (nearest or requested expiry) from the latest F&O bhavcopy."""
    inst, problem = _fno_instrument(symbol)
    if problem:
        return problem
    exchange = inst.fno_exchange
    sessions = recent_fo_sessions(_as_date(curr_date), 1, exchange)
    if not sessions:
        raise NoMarketDataError(
            symbol, inst.underlying, f"no {exchange} F&O bhavcopy found on or before {curr_date}"
        )
    day, frame = sessions[0]
    title = f"# Option chain: {inst.underlying} ({exchange} F&O, EOD bhavcopy {day.isoformat()})"
    options = _select(frame, inst, _OPTION_TYPES)
    if options.empty:
        return (
            f"{title}\n\n{inst.underlying} has no options in the {exchange} F&O bhavcopy for "
            f"{day.isoformat()}: it is not in the derivatives segment, so there is no option chain."
        )

    upcoming = sorted(e for e in set(options["XpryDt"]) if e >= day)
    expiry, note = _pick_expiry(options["XpryDt"], inst, day)
    if expiry is None:
        return f"{title}\n\n{note}. Listed expiries: {', '.join(e.isoformat() for e in upcoming[:8])}."

    rows = options[options["XpryDt"] == expiry]
    chain = build_option_chain(rows)
    spot = _num(rows["UndrlygPric"].median())
    lot = _lot_size(rows)
    days_left = (expiry - day).days
    rate = _risk_free_rate()
    m = chain_metrics(chain, spot, days_left, rate)
    all_calls = options[options["OptnTp"] == "CE"]["OpnIntrst"].sum()
    all_puts = options[options["OptnTp"] == "PE"]["OpnIntrst"].sum()

    lines = [title, ""]
    lines.append(
        f"Expiry analysed: {expiry.isoformat()} ({days_left} days) | Underlying: {_fmt(spot)} | "
        f"Lot size: {lot or 'n/a'} units | Upcoming expiries: {', '.join(e.isoformat() for e in upcoming[:6])}"
    )
    lines += ["", "## Key metrics"]
    lines.append(
        f"- Put-call ratio (OI): {_fmt(m['pcr_oi'])} | PCR (volume): {_fmt(m['pcr_volume'])} | "
        f"PCR (OI) across all expiries: {_fmt(all_puts / all_calls if all_calls else None)}"
    )
    lines.append(
        f"- Total call OI {_fmt(m['call_oi'], ',.0f')} ({_fmt(m['call_oi_change'], '+,.0f')}) vs put OI "
        f"{_fmt(m['put_oi'], ',.0f')} ({_fmt(m['put_oi_change'], '+,.0f')}) contracts"
    )
    lines.append(
        f"- Max pain: {_strike(m['max_pain'])} "
        f"({_signed_pct((m['max_pain'] - spot) / spot * 100 if m['max_pain'] and spot else None)} vs underlying)"
    )
    lines.append(
        f"- ATM strike {_strike(m['atm'])}: straddle premium {_fmt(m['straddle'])} → market-implied move "
        f"≈ ±{_fmt(m['implied_move_pct'])}% by expiry"
        + (f" | ATM implied volatility ≈ {m['atm_iv'] * 100:.1f}%" if m["atm_iv"] else "")
    )
    lines.append(f"- Highest call OI (resistance): {_strike_list(chain.nlargest(3, 'ce_oi'), 'ce_oi')}")
    lines.append(f"- Highest put OI (support): {_strike_list(chain.nlargest(3, 'pe_oi'), 'pe_oi')}")
    lines.append(f"- Largest call OI additions: {_strike_list(chain[chain['ce_chg'] > 0].nlargest(3, 'ce_chg'), 'ce_chg')}")
    lines.append(f"- Largest put OI additions: {_strike_list(chain[chain['pe_chg'] > 0].nlargest(3, 'pe_chg'), 'pe_chg')}")
    lines.append(f"- Largest call OI reductions: {_strike_list(chain[chain['ce_chg'] < 0].nsmallest(3, 'ce_chg'), 'ce_chg')}")
    lines.append(f"- Largest put OI reductions: {_strike_list(chain[chain['pe_chg'] < 0].nsmallest(3, 'pe_chg'), 'pe_chg')}")

    later = [e for e in upcoming if e > expiry]
    if later:
        next_rows = options[options["XpryDt"] == later[0]]
        next_chain = build_option_chain(next_rows)
        nm = chain_metrics(next_chain, spot, (later[0] - day).days, rate)
        lines.append(
            f"- Next expiry {later[0].isoformat()}: PCR (OI) {_fmt(nm['pcr_oi'])}, max pain "
            f"{_strike(nm['max_pain'])}, highest call OI {_strike(next_chain['ce_oi'].idxmax())}, "
            f"highest put OI {_strike(next_chain['pe_oi'].idxmax())}"
        )

    if inst.strike is not None and inst.option_type:
        lines += _contract_section(chain, inst, spot, days_left, rate, lot)

    if m["atm"] is not None:
        strikes = chain.index.to_list()
        position = strikes.index(m["atm"])
        window = chain.iloc[max(0, position - strikes_around_atm): position + strikes_around_atm + 1]
        years = days_left / 365 if days_left > 0 else None
        lines += [
            "",
            f"## Chain around the money ({expiry.isoformat()})",
            "",
            "| Call OI | Call ΔOI | Call LTP | Call IV % | Strike | Put IV % | Put LTP | Put ΔOI | Put OI |",
            "|---:|---:|---:|---:|:---:|---:|---:|---:|---:|",
        ]
        for strike, row in window.iterrows():
            call_iv = implied_volatility(row["ce_px"], spot, strike, years, rate, "CE") if years else None
            put_iv = implied_volatility(row["pe_px"], spot, strike, years, rate, "PE") if years else None
            label = f"**{_strike(strike)}**" if strike == m["atm"] else _strike(strike)
            lines.append(
                f"| {_fmt(row['ce_oi'], ',.0f')} | {_fmt(row['ce_chg'], '+,.0f')} | {_fmt(row['ce_px'])} | "
                f"{_fmt(call_iv * 100 if call_iv else None, '.1f')} | {label} | "
                f"{_fmt(put_iv * 100 if put_iv else None, '.1f')} | {_fmt(row['pe_px'])} | "
                f"{_fmt(row['pe_chg'], '+,.0f')} | {_fmt(row['pe_oi'], ',.0f')} |"
            )

    lines += [
        "",
        "Notes: end-of-day exchange data; OI and ΔOI in contracts. LTP is the session close (settlement "
        "price when the contract did not trade). IV is solved with Black-Scholes from closing premiums "
        f"(risk-free rate {rate:.2%}) and is unreliable for illiquid strikes. PCR = put OI ÷ call OI. "
        "Max pain is the expiry level where option holders' total intrinsic payout is lowest.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Participant-wise open interest (FII / DII / Pro / Client)
# ---------------------------------------------------------------------------


def parse_participant_oi(text: str) -> pd.DataFrame:
    """Parse NSE's participant-wise OI CSV into a frame indexed by participant."""
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.strip().strip('"').lower().startswith("client type")),
        None,
    )
    if start is None:
        raise ValueError("participant OI file has no 'Client Type' header row")
    frame = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    frame.columns = [str(column).strip() for column in frame.columns]
    frame["Client Type"] = frame["Client Type"].astype(str).str.strip()
    frame = frame.set_index("Client Type")
    return frame.apply(pd.to_numeric, errors="coerce")


def load_participant_oi(day: date) -> pd.DataFrame | None:
    dmy = day.strftime("%d%m%Y")
    group, name = "nse_participant_oi", f"{dmy}.csv"
    raw = fetch_archive(PARTICIPANT_OI_URL.format(dmy=dmy), group=group, name=name, trade_day=day)
    if raw is None:
        return None
    try:
        return parse_participant_oi(raw.decode("utf-8", errors="replace"))
    except (ValueError, KeyError, pd.errors.ParserError) as exc:
        logger.warning("Unreadable participant OI file for %s: %s", day, exc)
        invalidate_archive(group, name)
        return None


def _participant_value(frame: pd.DataFrame, participant: str, column: str) -> float | None:
    if participant not in frame.index:
        return None
    wanted = column.replace(" ", "").lower()
    for actual in frame.columns:
        if actual.replace(" ", "").lower() == wanted:
            return _num(frame.at[participant, actual])
    return None


def participant_oi_analysis(curr_date: str, look_back_days: int = 5) -> str:
    """FII / DII / Pro / Client derivatives positioning over recent sessions."""
    wanted = max(1, min(int(look_back_days or 5), 10))
    sessions: list[tuple[date, pd.DataFrame]] = []
    for day in weekdays_back(_as_date(curr_date), max_days=wanted * 2 + 12):
        frame = load_participant_oi(day)
        if frame is not None and not frame.empty:
            sessions.append((day, frame))
            if len(sessions) >= wanted:
                break
    if not sessions:
        raise NoMarketDataError(
            "NSE participant-wise OI", None, f"no file published on or before {curr_date}"
        )

    latest_day, latest = sessions[0]
    lines = [
        f"# NSE participant-wise open interest (contracts) — as of {latest_day.isoformat()}",
        "",
        "| Participant | Index fut long | Index fut short | Net | Long % | Index call net | Index put net | Stock fut net |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for participant in _PARTICIPANTS:
        long_ = _participant_value(latest, participant, "Future Index Long")
        short = _participant_value(latest, participant, "Future Index Short")
        if long_ is None or short is None:
            continue
        call_net = (_participant_value(latest, participant, "Option Index Call Long") or 0) - (
            _participant_value(latest, participant, "Option Index Call Short") or 0)
        put_net = (_participant_value(latest, participant, "Option Index Put Long") or 0) - (
            _participant_value(latest, participant, "Option Index Put Short") or 0)
        stock_net = (_participant_value(latest, participant, "Future Stock Long") or 0) - (
            _participant_value(latest, participant, "Future Stock Short") or 0)
        total = long_ + short
        lines.append(
            f"| {participant} | {long_:,.0f} | {short:,.0f} | {long_ - short:+,.0f} | "
            f"{_fmt(long_ / total * 100 if total else None, '.1f')} | {call_net:+,.0f} | "
            f"{put_net:+,.0f} | {stock_net:+,.0f} |"
        )

    lines += [
        "",
        "## Index-futures positioning trend",
        "",
        "| Date | FII long % | FII net | FII Δnet | Client net | Pro net | DII net |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    previous_fii = None
    for day, frame in reversed(sessions):
        def net(participant, frame=frame):
            long_ = _participant_value(frame, participant, "Future Index Long")
            short = _participant_value(frame, participant, "Future Index Short")
            return None if long_ is None or short is None else long_ - short

        fii_long = _participant_value(frame, "FII", "Future Index Long")
        fii_short = _participant_value(frame, "FII", "Future Index Short")
        fii_net = net("FII")
        long_pct = fii_long / (fii_long + fii_short) * 100 if fii_long is not None and fii_short else None
        delta = fii_net - previous_fii if fii_net is not None and previous_fii is not None else None
        previous_fii = fii_net
        lines.append(
            f"| {day.isoformat()} | {_fmt(long_pct, '.1f')} | {_fmt(fii_net, '+,.0f')} | "
            f"{_fmt(delta, '+,.0f')} | {_fmt(net('Client'), '+,.0f')} | {_fmt(net('Pro'), '+,.0f')} | "
            f"{_fmt(net('DII'), '+,.0f')} |"
        )
    lines += [
        "",
        "Notes: net = long − short contracts. Option nets are bought minus written contracts, so a "
        "negative put net means that participant is a net put writer. Clients (retail) are often on the "
        "opposite side of FIIs; the FII long % trend over several sessions matters more than one day.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# India VIX
# ---------------------------------------------------------------------------


def india_vix_analysis(curr_date: str) -> str:
    """India VIX level, change, one-year percentile and implied NIFTY move."""
    from ..stockstats_utils import load_ohlcv

    data = load_ohlcv(INDICES["INDIAVIX"].yahoo, curr_date)
    closes = data.set_index("Date")["Close"].dropna()
    if closes.empty:
        raise NoMarketDataError("INDIAVIX", "^INDIAVIX", "no India VIX closes")
    last = float(closes.iloc[-1])
    last_day = closes.index[-1].date()
    year = closes[closes.index > closes.index[-1] - pd.Timedelta(days=365)]

    def change(sessions: int) -> float | None:
        if len(closes) <= sessions:
            return None
        base = float(closes.iloc[-1 - sessions])
        return (last - base) / base * 100 if base else None

    lines = [
        f"# India VIX — as of {last_day.isoformat()}",
        "",
        f"- Close {last:.2f} (1 session {_signed_pct(change(1))}, 5 sessions {_signed_pct(change(5))}, "
        f"20 sessions {_signed_pct(change(20))})",
        f"- 20-session average {closes.tail(20).mean():.2f}; one-year range {year.min():.2f}–{year.max():.2f}; "
        f"one-year percentile {(year <= last).mean() * 100:.0f}",
        f"- Implied 1-sigma NIFTY move: ≈ ±{last * sqrt(30 / 365):.2f}% over 30 days, "
        f"≈ ±{last / sqrt(252):.2f}% per trading day",
        "",
        "| Date | India VIX |",
        "|---|---:|",
    ]
    for stamp, value in closes.tail(10).items():
        lines.append(f"| {stamp.date().isoformat()} | {value:.2f} |")
    lines += [
        "",
        "Notes: India VIX is the annualised 30-day volatility implied by NIFTY option prices. A rising VIX "
        "alongside falling prices signals hedging demand and fear; a low VIX signals complacency and "
        "cheaper options.",
    ]
    return "\n".join(lines)


def _is_index_segment(inst: IndianInstrument) -> bool:
    return inst.segment == INDEX or inst.underlying_kind == "index"


__all__ = [
    "bs_price",
    "build_option_chain",
    "chain_metrics",
    "classify_buildup",
    "futures_analysis",
    "implied_volatility",
    "india_vix_analysis",
    "load_fo_bhavcopy",
    "max_pain_strike",
    "option_chain_analysis",
    "option_greeks",
    "parse_fo_bhavcopy",
    "parse_participant_oi",
    "participant_oi_analysis",
    "recent_fo_sessions",
    "resolve_contract",
]
