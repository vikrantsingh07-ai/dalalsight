"""Indian market instruments: one parser for NSE / BSE / MCX / NSE-CDS symbol forms.

Users type Indian instruments in several broker conventions. Every form resolves
to a single :class:`IndianInstrument`:

    input                          segment     OHLCV tools price
    -----------------------------  ----------  ---------------------------------
    RELIANCE.NS, 500325.BO         equity      the Yahoo symbol itself
    RELIANCE          (india mode) equity      RELIANCE.NS
    NIFTY, BANKNIFTY, ^NSEI        index       ^NSEI, ^NSEBANK, ...
    NIFTY26SEPFUT, RELIANCE-FUT    futures     the underlying (^NSEI, RELIANCE.NS)
    NIFTY26SEP23500CE              options     the underlying; monthly contract
    NIFTY2691523500CE              options     weekly contract (YY, M=1-9/O/N/D, DD)
    NIFTY-OPT                      options     option-chain view, nearest expiry
    GOLD (india mode), GOLD.MCX,   commodity   MCX proxy series (commodities.py)
      CRUDEOIL26SEPFUT
    USDINR, USDINR26SEPFUT         currency    USDINR=X spot

Parsing is purely syntactic (no network), so it is safe on every call. Contract
facts that need exchange data (actual expiry date, lot size, open interest) are
resolved separately from the exchange bhavcopy in ``fno.py``.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

from ..symbol_utils import _ALIASES, _FOREX_CURRENCIES, crypto_base

EQUITY = "equity"
INDEX = "index"
FUTURES = "futures"
OPTIONS = "options"
COMMODITY = "commodity"
CURRENCY = "currency"

SEGMENTS = (EQUITY, INDEX, FUTURES, OPTIONS, COMMODITY, CURRENCY)


@dataclass(frozen=True)
class IndexSpec:
    yahoo: str
    # Also the "Index Name" used in NSE's daily index-close file.
    name: str
    exchange: str
    has_derivatives: bool = False


INDICES: dict[str, IndexSpec] = {
    # Indices with exchange-traded futures and options.
    "NIFTY": IndexSpec("^NSEI", "Nifty 50", "NSE", True),
    "BANKNIFTY": IndexSpec("^NSEBANK", "Nifty Bank", "NSE", True),
    "FINNIFTY": IndexSpec("NIFTY_FIN_SERVICE.NS", "Nifty Financial Services", "NSE", True),
    "MIDCPNIFTY": IndexSpec("NIFTY_MID_SELECT.NS", "Nifty Midcap Select", "NSE", True),
    "NIFTYNXT50": IndexSpec("^NSMIDCP", "Nifty Next 50", "NSE", True),
    "SENSEX": IndexSpec("^BSESN", "BSE Sensex", "BSE", True),
    "BANKEX": IndexSpec("BSE-BANK.BO", "BSE Bankex", "BSE", True),
    # Cash / sectoral indices (no derivatives).
    "INDIAVIX": IndexSpec("^INDIAVIX", "India VIX", "NSE"),
    "NIFTYIT": IndexSpec("^CNXIT", "Nifty IT", "NSE"),
    "NIFTYPHARMA": IndexSpec("^CNXPHARMA", "Nifty Pharma", "NSE"),
    "NIFTYAUTO": IndexSpec("^CNXAUTO", "Nifty Auto", "NSE"),
    "NIFTYFMCG": IndexSpec("^CNXFMCG", "Nifty FMCG", "NSE"),
    "NIFTYMETAL": IndexSpec("^CNXMETAL", "Nifty Metal", "NSE"),
    "NIFTYREALTY": IndexSpec("^CNXREALTY", "Nifty Realty", "NSE"),
    "NIFTYENERGY": IndexSpec("^CNXENERGY", "Nifty Energy", "NSE"),
    "NIFTYPSUBANK": IndexSpec("^CNXPSUBANK", "Nifty PSU Bank", "NSE"),
    "NIFTYMEDIA": IndexSpec("^CNXMEDIA", "Nifty Media", "NSE"),
    "NIFTYINFRA": IndexSpec("^CNXINFRA", "Nifty Infrastructure", "NSE"),
    "NIFTYPVTBANK": IndexSpec("NIFTY_PVT_BANK.NS", "Nifty Private Bank", "NSE"),
    "NIFTYMIDCAP100": IndexSpec("NIFTY_MIDCAP_100.NS", "NIFTY Midcap 100", "NSE"),
    "NIFTYSMALLCAP100": IndexSpec("^CNXSC", "NIFTY Smallcap 100", "NSE"),
    "NIFTYMIDCAP50": IndexSpec("^NSEMDCP50", "Nifty Midcap 50", "NSE"),
}

_INDEX_ALIASES = {
    "NIFTY50": "NIFTY",
    "NIFTY_50": "NIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "NIFTYFIN": "FINNIFTY",
    "MIDCAPNIFTY": "MIDCPNIFTY",
    "NIFTYNEXT50": "NIFTYNXT50",
    "BSESENSEX": "SENSEX",
    "INDIA_VIX": "INDIAVIX",
}

_YAHOO_TO_INDEX = {spec.yahoo: key for key, spec in INDICES.items()}


@dataclass(frozen=True)
class CommoditySpec:
    # Yahoo global benchmark future the MCX proxy is built from (None = no proxy).
    global_symbol: str | None
    # MCX quotation unit, and the factor converting "USD quote x USDINR" into it.
    unit: str
    factor: float
    name: str


_GRAMS_PER_TROY_OUNCE = 31.1034768
_POUNDS_PER_KG = 2.20462262

COMMODITIES: dict[str, CommoditySpec] = {
    "GOLD": CommoditySpec("GC=F", "INR per 10 grams", 10 / _GRAMS_PER_TROY_OUNCE, "Gold"),
    "GOLDM": CommoditySpec("GC=F", "INR per 10 grams", 10 / _GRAMS_PER_TROY_OUNCE, "Gold Mini"),
    "GOLDTEN": CommoditySpec("GC=F", "INR per 10 grams", 10 / _GRAMS_PER_TROY_OUNCE, "Gold Ten"),
    "GOLDGUINEA": CommoditySpec("GC=F", "INR per 8 grams", 8 / _GRAMS_PER_TROY_OUNCE, "Gold Guinea"),
    "GOLDPETAL": CommoditySpec("GC=F", "INR per gram", 1 / _GRAMS_PER_TROY_OUNCE, "Gold Petal"),
    "SILVER": CommoditySpec("SI=F", "INR per kg", 1000 / _GRAMS_PER_TROY_OUNCE, "Silver"),
    "SILVERM": CommoditySpec("SI=F", "INR per kg", 1000 / _GRAMS_PER_TROY_OUNCE, "Silver Mini"),
    "SILVERMIC": CommoditySpec("SI=F", "INR per kg", 1000 / _GRAMS_PER_TROY_OUNCE, "Silver Micro"),
    "CRUDEOIL": CommoditySpec("CL=F", "INR per barrel", 1.0, "Crude Oil"),
    "CRUDEOILM": CommoditySpec("CL=F", "INR per barrel", 1.0, "Crude Oil Mini"),
    "NATURALGAS": CommoditySpec("NG=F", "INR per mmBtu", 1.0, "Natural Gas"),
    "NATGASMINI": CommoditySpec("NG=F", "INR per mmBtu", 1.0, "Natural Gas Mini"),
    "COPPER": CommoditySpec("HG=F", "INR per kg", _POUNDS_PER_KG, "Copper"),
    "ALUMINIUM": CommoditySpec("ALI=F", "INR per kg", 1 / 1000, "Aluminium"),
    "ALUMINI": CommoditySpec("ALI=F", "INR per kg", 1 / 1000, "Aluminium Mini"),
    # Base metals with no liquid free global benchmark on Yahoo.
    "ZINC": CommoditySpec(None, "INR per kg", 0.0, "Zinc"),
    "ZINCMINI": CommoditySpec(None, "INR per kg", 0.0, "Zinc Mini"),
    "LEAD": CommoditySpec(None, "INR per kg", 0.0, "Lead"),
    "LEADMINI": CommoditySpec(None, "INR per kg", 0.0, "Lead Mini"),
    "NICKEL": CommoditySpec(None, "INR per kg", 0.0, "Nickel"),
}


@dataclass(frozen=True)
class CurrencySpec:
    yahoo: str
    note: str


CURRENCIES: dict[str, CurrencySpec] = {
    "USDINR": CurrencySpec("USDINR=X", "INR per US dollar"),
    "EURINR": CurrencySpec("EURINR=X", "INR per euro"),
    "GBPINR": CurrencySpec("GBPINR=X", "INR per pound sterling"),
    "JPYINR": CurrencySpec(
        "JPYINR=X",
        "Yahoo quotes INR per 1 yen; the NSE JPYINR contract is quoted per 100 yen",
    ),
}


@dataclass(frozen=True)
class IndianInstrument:
    # Canonical symbol the pipeline carries (what the user analyses).
    symbol: str
    segment: str
    # Exchange underlying code: NIFTY, RELIANCE, GOLD, USDINR, 500325.
    underlying: str
    underlying_kind: str  # index | stock | commodity | currency
    exchange: str  # NSE | BSE | MCX | NSE-CDS
    # Symbol the OHLCV / indicator tools price (Yahoo symbol or MCX proxy).
    price_symbol: str
    # Real Yahoo symbol for news and identity lookups.
    reference_symbol: str
    name: str | None = None
    contract: str | None = None  # "FUT" | "OPT" for a derivative contract
    expiry_year: int | None = None
    expiry_month: int | None = None
    expiry_day: int | None = None  # weekly option symbols only
    strike: float | None = None
    option_type: str | None = None  # "CE" | "PE"

    @property
    def fno_exchange(self) -> str:
        """Exchange whose F&O bhavcopy lists this underlying's derivatives."""
        spec = INDICES.get(self.underlying)
        return spec.exchange if spec else "NSE"

    @property
    def supports_exchange_derivatives(self) -> bool:
        """Whether NSE/BSE equity-derivative data can exist for this instrument."""
        if self.segment in (FUTURES, OPTIONS):
            return True
        if self.segment == INDEX:
            return INDICES[self.underlying].has_derivatives
        return self.segment == EQUITY and self.exchange == "NSE"

    def expiry_label(self) -> str | None:
        if self.expiry_day:
            return date(self.expiry_year, self.expiry_month, self.expiry_day).isoformat()
        if self.expiry_month:
            return f"{calendar.month_abbr[self.expiry_month]} {self.expiry_year} monthly expiry"
        if self.contract:
            return "nearest listed expiry"
        return None


def asset_type_for(instrument: IndianInstrument) -> str:
    """Pipeline ``asset_type``: cash equities keep the existing ``stock`` mode."""
    return "stock" if instrument.segment == EQUITY else instrument.segment


def is_india_mode() -> bool:
    """True when the active config selects the Indian market (``market: india``)."""
    from ..config import get_config  # lazy: config imports default_config

    try:
        market = get_config().get("market")
    except Exception:  # noqa: BLE001 — a config problem must not break symbol parsing
        return False
    return str(market or "").strip().lower() in ("india", "in")


_MONTHS = {
    abbr: number
    for number, abbr in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
        start=1,
    )
}
_MONTH_PATTERN = "|".join(_MONTHS)
_WEEKLY_MONTHS = {**{str(n): n for n in range(1, 10)}, "O": 10, "N": 11, "D": 12}

# NSE symbols: letters, digits, '&' (M&M) and '-' (BAJAJ-AUTO). Non-greedy so the
# anchored expiry/strike tail decides where the underlying ends.
_UNDERLYING = r"(?P<u>[A-Z0-9][A-Z0-9&\-]*?)"
_GENERIC_RE = re.compile(rf"^{_UNDERLYING}-(?P<kind>FUT|OPT)$")
_MONTHLY_FUT_RE = re.compile(rf"^{_UNDERLYING}(?P<yy>\d{{2}})(?P<mon>{_MONTH_PATTERN})FUT$")
_MONTHLY_OPT_RE = re.compile(
    rf"^{_UNDERLYING}(?P<yy>\d{{2}})(?P<mon>{_MONTH_PATTERN})"
    r"(?P<strike>\d+(?:\.\d+)?)(?P<ot>CE|PE)$"
)
_WEEKLY_OPT_TAIL_RE = re.compile(
    r"^(?P<yy>\d{2})(?P<m>[1-9OND])(?P<dd>\d{2})(?P<strike>\d+(?:\.\d+)?)(?P<ot>CE|PE)$"
)
_BARE_EQUITY_RE = re.compile(r"^[A-Z0-9][A-Z0-9&\-]{0,19}$")
# Weekly options exist only on index underlyings; longest first so FINNIFTY is
# tried before NIFTY.
_WEEKLY_UNDERLYINGS = tuple(
    sorted((k for k, s in INDICES.items() if s.has_derivatives), key=len, reverse=True)
)


def _index(key: str) -> IndianInstrument:
    spec = INDICES[key]
    return IndianInstrument(
        symbol=key,
        segment=INDEX,
        underlying=key,
        underlying_kind="index",
        exchange=spec.exchange,
        price_symbol=spec.yahoo,
        reference_symbol=spec.yahoo,
        name=spec.name,
    )


def _commodity(code: str, symbol: str, **contract_fields) -> IndianInstrument:
    spec = COMMODITIES[code]
    proxy = f"{code}.MCX"
    return IndianInstrument(
        symbol=symbol,
        segment=COMMODITY,
        underlying=code,
        underlying_kind="commodity",
        exchange="MCX",
        price_symbol=proxy,
        reference_symbol=spec.global_symbol or proxy,
        name=spec.name,
        **contract_fields,
    )


def _currency(pair: str, symbol: str, **contract_fields) -> IndianInstrument:
    spec = CURRENCIES[pair]
    return IndianInstrument(
        symbol=symbol,
        segment=CURRENCY,
        underlying=pair,
        underlying_kind="currency",
        exchange="NSE-CDS",
        price_symbol=spec.yahoo,
        reference_symbol=spec.yahoo,
        name=pair,
        **contract_fields,
    )


def _derivative(underlying: str, symbol: str, contract: str, **fields) -> IndianInstrument | None:
    if underlying in COMMODITIES:
        return _commodity(underlying, symbol, contract=contract, **fields)
    if underlying in CURRENCIES:
        return _currency(underlying, symbol, contract=contract, **fields)
    segment = FUTURES if contract == "FUT" else OPTIONS
    key = _INDEX_ALIASES.get(underlying, underlying)
    if key in INDICES:
        spec = INDICES[key]
        if not spec.has_derivatives:
            return None
        return IndianInstrument(
            symbol=symbol,
            segment=segment,
            underlying=key,
            underlying_kind="index",
            exchange=spec.exchange,
            price_symbol=spec.yahoo,
            reference_symbol=spec.yahoo,
            name=spec.name,
            contract=contract,
            **fields,
        )
    if not _BARE_EQUITY_RE.fullmatch(underlying):
        return None
    cash = f"{underlying}.NS"
    return IndianInstrument(
        symbol=symbol,
        segment=segment,
        underlying=underlying,
        underlying_kind="stock",
        exchange="NSE",
        price_symbol=cash,
        reference_symbol=cash,
        contract=contract,
        **fields,
    )


def _parse_derivative(s: str) -> IndianInstrument | None:
    match = _GENERIC_RE.fullmatch(s)
    if match:
        return _derivative(match["u"], s, match["kind"])

    match = _MONTHLY_FUT_RE.fullmatch(s)
    if match:
        return _derivative(
            match["u"], s, "FUT",
            expiry_year=2000 + int(match["yy"]),
            expiry_month=_MONTHS[match["mon"]],
        )

    match = _MONTHLY_OPT_RE.fullmatch(s)
    if match:
        return _derivative(
            match["u"], s, "OPT",
            expiry_year=2000 + int(match["yy"]),
            expiry_month=_MONTHS[match["mon"]],
            strike=float(match["strike"]),
            option_type=match["ot"],
        )

    for underlying in _WEEKLY_UNDERLYINGS:
        if not s.startswith(underlying):
            continue
        tail = _WEEKLY_OPT_TAIL_RE.fullmatch(s[len(underlying):])
        if not tail:
            continue
        year, month, day = 2000 + int(tail["yy"]), _WEEKLY_MONTHS[tail["m"]], int(tail["dd"])
        try:
            date(year, month, day)
        except ValueError:
            continue
        return _derivative(
            underlying, s, "OPT",
            expiry_year=year, expiry_month=month, expiry_day=day,
            strike=float(tail["strike"]), option_type=tail["ot"],
        )
    return None


def _is_global_symbol(s: str) -> bool:
    """Symbols that keep their global meaning even in India mode."""
    if s in _ALIASES or crypto_base(s) is not None:
        return True
    return len(s) == 6 and s[:3] in _FOREX_CURRENCIES and s[3:] in _FOREX_CURRENCIES


def parse_indian_symbol(raw: str, *, india_mode: bool | None = None) -> IndianInstrument | None:
    """Parse ``raw`` into an :class:`IndianInstrument`, or None if it is not Indian.

    Exchange-suffixed symbols, Indian index names, INR currency pairs and
    derivative contract symbols are recognised in every mode. Bare commodity
    names (GOLD means COMEX gold globally) and bare NSE equities (RELIANCE) are
    recognised only in India mode.
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip().upper().rstrip("+")
    if not s:
        return None
    if india_mode is None:
        india_mode = is_india_mode()

    key = _YAHOO_TO_INDEX.get(s)
    if key is not None:
        return _index(key)

    if s.endswith((".NS", ".BO")):
        base = s[:-3]
        if not base:
            return None
        return IndianInstrument(
            symbol=s,
            segment=EQUITY,
            underlying=base,
            underlying_kind="stock",
            exchange="NSE" if s.endswith(".NS") else "BSE",
            price_symbol=s,
            reference_symbol=s,
        )

    if s.endswith(".MCX"):
        base = s[:-4]
        if base in COMMODITIES:
            return _commodity(base, s)
        contract = _parse_derivative(base)
        return contract if contract is not None and contract.segment == COMMODITY else None

    key = _INDEX_ALIASES.get(s, s)
    if key in INDICES:
        return _index(key)

    if s in CURRENCIES:
        return _currency(s, s)

    contract = _parse_derivative(s)
    if contract is not None:
        return contract

    if not india_mode:
        return None
    if s in COMMODITIES:
        return _commodity(s, f"{s}.MCX")
    if _BARE_EQUITY_RE.fullmatch(s) and not _is_global_symbol(s):
        cash = f"{s}.NS"
        return IndianInstrument(
            symbol=cash,
            segment=EQUITY,
            underlying=s,
            underlying_kind="stock",
            exchange="NSE",
            price_symbol=cash,
            reference_symbol=cash,
        )
    return None


def _underlying_label(inst: IndianInstrument) -> str:
    if inst.underlying_kind == "index" and inst.name:
        return f"{inst.name} ({inst.underlying})"
    return inst.underlying


def describe_instrument(inst: IndianInstrument, contract: dict | None = None) -> str:
    """Market-specific guidance appended to the instrument context for every agent."""
    venue = {
        "NSE": "NSE",
        "BSE": "BSE",
        "MCX": "MCX (Multi Commodity Exchange)",
        "NSE-CDS": "NSE currency derivatives",
    }.get(inst.exchange, inst.exchange)
    parts = [
        f"Market: India ({venue}). Prices are in Indian rupees (INR, ₹) unless a tool states otherwise."
    ]
    if inst.segment in (EQUITY, INDEX, FUTURES, OPTIONS):
        parts.append(
            "NSE/BSE equity sessions run 09:15-15:30 IST; cash trades settle T+1; "
            "exchange price bands and index-wide circuit breakers can cap daily moves."
        )

    price_tools = "Price/indicator tools (get_stock_data, get_indicators, get_verified_market_snapshot)"
    if inst.segment == EQUITY:
        parts.append(
            f"Segment: cash equity ({inst.exchange}: {inst.underlying}). "
            "Delivery-based buying is the unleveraged way to hold it; if the stock is in the NSE "
            "F&O segment, its futures and options positioning is also relevant."
        )
    elif inst.segment == INDEX:
        if inst.underlying == "INDIAVIX":
            parts.append(
                "Segment: volatility index. India VIX is derived from NIFTY option prices and is not "
                "directly tradable; read it as the market's expected 30-day NIFTY volatility."
            )
        else:
            spec = INDICES[inst.underlying]
            route = (
                f"index futures/options on {spec.exchange} or an index ETF"
                if spec.has_derivatives else "an index fund or ETF"
            )
            parts.append(
                f"Segment: index ({_underlying_label(inst)}). An index cannot be bought directly: "
                f"express the view through {route}, and quote levels in index points."
            )
    elif inst.segment == FUTURES:
        kind = "index" if inst.underlying_kind == "index" else "stock"
        parts.append(
            f"Segment: {kind} futures on {_underlying_label(inst)} ({inst.expiry_label()}). "
            f"{price_tools} return the UNDERLYING spot series ({inst.price_symbol}); the futures "
            "price, basis, open interest and lot size come from the derivatives tools. State entry "
            "and stop-loss as futures price levels and size positions in whole lots. Futures are "
            "leveraged (SPAN + exposure margin), marked to market daily, and must be rolled or "
            "closed before expiry."
        )
    elif inst.segment == OPTIONS:
        if inst.strike is not None and inst.option_type:
            side = "call (CE)" if inst.option_type == "CE" else "put (PE)"
            parts.append(
                f"Segment: option contract — {side}, strike {inst.strike:g}, {inst.expiry_label()}, "
                f"on {_underlying_label(inst)}. The Buy/Hold/Sell call, entry, stop-loss and target "
                "refer to this option's PREMIUM in INR, not the underlying's price. "
                f"{price_tools} return the UNDERLYING spot series ({inst.price_symbol}); premium, open "
                "interest, implied volatility and Greeks come from the derivatives tools. Weigh time "
                "decay (theta), implied volatility and lot size: an option buyer can lose the whole "
                "premium, while an option writer faces large losses and high margin."
            )
        else:
            parts.append(
                f"Segment: options on {_underlying_label(inst)} (option-chain view, "
                f"{inst.expiry_label()}). Use the option chain to judge whether a directional option "
                "buy, a spread, option writing or no trade fits the outlook, and name the specific "
                f"strike(s) and expiry in the plan. {price_tools} return the UNDERLYING spot series "
                f"({inst.price_symbol})."
            )
    elif inst.segment == COMMODITY:
        spec = COMMODITIES[inst.underlying]
        contract_text = ""
        if inst.contract == "FUT":
            contract_text = f" futures ({inst.expiry_label()})"
        elif inst.contract == "OPT":
            contract_text = f" options ({inst.expiry_label()})"
        if spec.global_symbol:
            parts.append(
                f"Segment: MCX commodity — {spec.name}{contract_text}, quoted {spec.unit}. No free MCX "
                "price feed exists, so price/indicator tools return a PROXY series: the global "
                f"benchmark {spec.global_symbol} converted at the USD/INR rate into {spec.unit}. The "
                "proxy leaves out Indian import duty, GST and local premiums, so its absolute level "
                "differs from the MCX quote while its trend and percentage moves track closely. State "
                "entry, stop-loss and targets as percentage distances from the current price (you may "
                "also show the proxy level) so they can be applied to the live MCX quote. MCX trades "
                "about 09:00-23:30 IST following global markets; contracts are leveraged and expire "
                "monthly."
            )
        else:
            parts.append(
                f"Segment: MCX commodity — {spec.name}{contract_text}, quoted {spec.unit}. No price "
                "proxy is available for it, so price tools report data as unavailable: rely on news "
                "and macro context and do not invent price levels."
            )
    elif inst.segment == CURRENCY:
        spec = CURRENCIES[inst.underlying]
        contract_text = f" futures ({inst.expiry_label()})" if inst.contract == "FUT" else ""
        parts.append(
            f"Segment: NSE currency derivatives — {inst.underlying}{contract_text} ({spec.note}). "
            f"Price tools return the spot rate {spec.yahoo}. The rupee is driven by RBI intervention "
            "and policy, crude oil prices, US dollar strength and foreign portfolio flows; NSE "
            "currency futures expire monthly."
        )

    if contract:
        details = [f"expiry {contract['expiry']} ({contract['days_to_expiry']} days after {contract['as_of']})"]
        if contract.get("lot_size"):
            details.append(f"lot size {contract['lot_size']} units")
        parts.append(f"Resolved contract from the exchange bhavcopy: {', '.join(details)}.")
    return " ".join(parts)
