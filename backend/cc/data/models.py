"""Provider-neutral data types shared by every market-data provider."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    return datetime.now(IST)


class DataUnavailable(Exception):
    """Raised when a provider cannot supply real data. Callers show "Data unavailable"."""

    def __init__(self, what: str, reason: str, source: str = "", requirement: str = ""):
        self.what = what
        self.reason = reason
        self.source = source
        self.requirement = requirement
        message = f"{what}: data unavailable ({reason})"
        if requirement:
            message += f"; requires {requirement}"
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "status": "unavailable",
            "what": self.what,
            "reason": self.reason,
            "source": self.source,
            "requirement": self.requirement,
        }


@dataclass
class Quote:
    symbol: str
    price: float
    prev_close: float | None
    open: float | None
    high: float | None
    low: float | None
    volume: float | None
    timestamp: datetime
    provider: str
    change: float | None = None
    change_pct: float | None = None
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.change is None and self.prev_close:
            self.change = self.price - self.prev_close
        if self.change_pct is None and self.prev_close:
            self.change_pct = (self.price - self.prev_close) / self.prev_close * 100

    def to_dict(self) -> dict:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class OptionLeg:
    ltp: float | None
    change: float | None
    change_pct: float | None
    volume: float | None
    oi: float | None
    oi_change: float | None
    oi_change_pct: float | None
    iv: float | None
    bid: float | None
    ask: float | None
    bid_qty: float | None
    ask_qty: float | None

    @property
    def mid(self) -> float | None:
        if self.bid and self.ask and self.ask >= self.bid:
            return (self.bid + self.ask) / 2
        return self.ltp

    @property
    def spread_pct(self) -> float | None:
        mid = self.mid
        if self.bid and self.ask and mid:
            return (self.ask - self.bid) / mid * 100
        return None


@dataclass
class OptionRow:
    strike: float
    ce: OptionLeg | None
    pe: OptionLeg | None


@dataclass
class OptionChain:
    symbol: str
    expiry: date
    spot: float
    timestamp: datetime
    provider: str
    rows: list[OptionRow]
    lot_size: int | None = None

    def strikes(self) -> list[float]:
        return [row.strike for row in self.rows]

    def row(self, strike: float) -> OptionRow | None:
        for row in self.rows:
            if abs(row.strike - strike) < 1e-6:
                return row
        return None

    def strike_step(self) -> float | None:
        strikes = sorted(self.strikes())
        diffs = sorted({round(b - a, 4) for a, b in zip(strikes, strikes[1:], strict=False) if b > a})
        return diffs[0] if diffs else None

    def atm_strike(self) -> float | None:
        strikes = self.strikes()
        return min(strikes, key=lambda k: abs(k - self.spot)) if strikes else None


@dataclass
class InstrumentMeta:
    symbol: str
    name: str
    kind: str  # index | stock
    exchange: str
    yahoo_symbol: str | None
    tradingview_symbol: str | None
    nse_index_name: str | None = None
    option_type: str | None = None  # Indices | Equity | None
    lot_size: int | None = None
    sector: str | None = None
    has_volume: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MarketStatus:
    session: str  # PRE_OPEN | OPEN | CLOSING | POST_CLOSE | CLOSED
    is_trading: bool
    label: str
    now: datetime
    session_date: date
    next_open: datetime | None
    reason: str
    exchange_message: str | None = None

    def to_dict(self) -> dict:
        return {
            "session": self.session,
            "is_trading": self.is_trading,
            "label": self.label,
            "now": self.now.isoformat(),
            "session_date": self.session_date.isoformat(),
            "next_open": self.next_open.isoformat() if self.next_open else None,
            "reason": self.reason,
            "exchange_message": self.exchange_message,
        }


@dataclass
class ProviderHealth:
    name: str
    status: str  # ONLINE | DEGRADED | OFFLINE | ERROR | NOT_CONFIGURED
    detail: str = ""
    last_success: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    latency_ms: float | None = None
    capabilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        for key in ("last_success", "last_error_at"):
            if data[key] is not None:
                data[key] = data[key].isoformat()
        return data
