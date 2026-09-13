"""Paper trading (simulated fills at real market prices). Live execution is refused."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..config import EnvConfig, RuntimeSettings
from ..data.models import DataUnavailable, now_ist
from ..data.symbols import SYMBOL_RE
from ..storage.db import Database
from .timeline import Timeline


class ExecutionRefused(Exception):
    pass


class PaperOrderIn(BaseModel):
    symbol: str = Field(max_length=32)
    side: Literal["BUY", "SELL"]
    quantity: float = Field(gt=0, le=10_000_000)
    instrument_type: Literal["underlying", "option"] = "underlying"
    expiry: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    strike: float | None = Field(None, gt=0)
    option_type: Literal["CE", "PE"] | None = None
    note: str | None = Field(None, max_length=200)

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not SYMBOL_RE.match(value):
            raise ValueError("invalid symbol")
        return value

    @model_validator(mode="after")
    def _option_fields(self) -> PaperOrderIn:
        if self.instrument_type == "option" and not (self.expiry and self.strike and self.option_type):
            raise ValueError("option orders need expiry, strike and option_type")
        return self

    @property
    def instrument(self) -> str:
        if self.instrument_type == "underlying":
            return self.symbol
        return f"{self.symbol} {self.expiry} {self.strike:g} {self.option_type}"


class PaperService:
    def __init__(self, db: Database, env: EnvConfig, settings: Callable[[], RuntimeSettings], analysis, options, timeline: Timeline):
        self.db = db
        self.env = env
        self.settings = settings
        self.analysis = analysis
        self.options = options
        self.timeline = timeline

    def _guard(self) -> None:
        mode = self.settings().execution_mode
        if mode == "live":
            if not self.env.live_execution_enabled:
                raise ExecutionRefused("LIVE execution is disabled (LIVE_EXECUTION_ENABLED=false). No order was sent.")
            raise ExecutionRefused("LIVE execution requires a broker execution adapter, which is not implemented. No order was sent.")
        if mode != "paper":
            raise ExecutionRefused("Execution mode is ANALYSIS. Switch to PAPER in Settings to record simulated orders.")

    def price(self, instrument: str) -> tuple[float, str]:
        parts = instrument.split()
        if len(parts) == 1:
            quote = self.analysis.provider.get_quote(parts[0])
            return quote.price, f"{quote.provider} quote at {quote.timestamp.isoformat()}"
        symbol, expiry, strike, option_type = parts
        chain = self.options.chain(symbol, expiry)
        row = chain.row(float(strike))
        leg = None if row is None else (row.ce if option_type == "CE" else row.pe)
        if leg is None or leg.mid is None:
            raise DataUnavailable(instrument, "no quote in the option chain", chain.provider)
        source = "bid/ask mid" if leg.bid and leg.ask else "last traded price"
        return round(leg.mid, 2), f"{chain.provider} {source} at {chain.timestamp.isoformat()}"

    def place(self, order: PaperOrderIn) -> dict:
        self._guard()
        price, source = self.price(order.instrument)
        ts = now_ist().isoformat()
        order_id = self.db.execute(
            "INSERT INTO paper_orders(ts, symbol, instrument, side, quantity, price, price_source, status, note) VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, order.symbol, order.instrument, order.side, order.quantity, price, source, "filled (simulated)", order.note),
        )
        self.timeline.add("paper", f"PAPER {order.side} {order.quantity:g} {order.instrument} @ {price:,.2f} ({source})", order.symbol)
        return {"id": order_id, "ts": ts, "instrument": order.instrument, "side": order.side, "quantity": order.quantity,
                "price": price, "price_source": source, "status": "filled (simulated)", "mode": "PAPER"}

    def orders(self, limit: int = 200) -> list[dict]:
        return self.db.query("SELECT * FROM paper_orders ORDER BY id DESC LIMIT ?", (limit,))

    def positions(self) -> list[dict]:
        books: dict[str, dict] = {}
        for order in self.db.query("SELECT * FROM paper_orders ORDER BY id"):
            book = books.setdefault(order["instrument"], {"instrument": order["instrument"], "symbol": order["symbol"], "quantity": 0.0,
                                                          "avg_price": 0.0, "realized_pnl": 0.0})
            signed = order["quantity"] if order["side"] == "BUY" else -order["quantity"]
            qty, avg, price = book["quantity"], book["avg_price"], order["price"]
            if qty == 0 or (qty > 0) == (signed > 0):
                book["avg_price"] = (avg * abs(qty) + price * abs(signed)) / (abs(qty) + abs(signed))
                book["quantity"] = qty + signed
            else:
                closing = min(abs(qty), abs(signed))
                book["realized_pnl"] += closing * (price - avg) * (1 if qty > 0 else -1)
                book["quantity"] = qty + signed
                if abs(signed) > abs(qty):
                    book["avg_price"] = price
                elif book["quantity"] == 0:
                    book["avg_price"] = 0.0
        out = []
        for book in books.values():
            mark = source = None
            if book["quantity"]:
                try:
                    mark, source = self.price(book["instrument"])
                except DataUnavailable as exc:
                    source = f"mark unavailable: {exc.reason}"
            unrealized = None if mark is None else round((mark - book["avg_price"]) * book["quantity"], 2)
            out.append({**book, "avg_price": round(book["avg_price"], 2), "realized_pnl": round(book["realized_pnl"], 2),
                        "mark": mark, "mark_source": source, "unrealized_pnl": unrealized})
        return out
