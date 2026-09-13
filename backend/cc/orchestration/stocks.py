"""Stock analysis, scanner and hedging data services."""

from __future__ import annotations

import contextlib
from collections.abc import Callable

import pandas as pd
import yfinance as yf

from ..analysis.hedging import HedgeRequest, beta_stats, hedge_plan
from ..analysis.options import analyze_chain
from ..analysis.scanner import PRESETS, compute_stock_metrics, run_preset, score_stock
from ..config import RuntimeSettings
from ..data.cache import TTLCache
from ..data.models import DataUnavailable, now_ist
from ..data.provider import MarketDataProvider
from ..data.symbols import SymbolRegistry
from .analysis import AnalysisService, OptionsService

FUNDAMENTAL_KEYS = [
    "longName", "sector", "industry", "marketCap", "trailingPE", "forwardPE", "priceToBook", "returnOnEquity",
    "returnOnAssets", "debtToEquity", "revenueGrowth", "earningsGrowth", "profitMargins", "operatingMargins",
    "dividendYield", "bookValue", "trailingEps", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "beta",
]
UNIVERSES = ("NIFTY 50", "NIFTY 100", "NIFTY NEXT 50", "FNO", "WATCHLIST")


class StockService:
    def __init__(self, provider: MarketDataProvider, registry: SymbolRegistry, settings: Callable[[], RuntimeSettings],
                 cache: TTLCache, analysis: AnalysisService, options: OptionsService):
        self.provider = provider
        self.registry = registry
        self.settings = settings
        self.cache = cache
        self.analysis = analysis
        self.options = options

    def fundamentals(self, symbol: str) -> dict:
        def load() -> dict:
            try:
                info = yf.Ticker(f"{symbol}.NS").info or {}
            except Exception as exc:  # noqa: BLE001
                return {"status": "unavailable", "reason": f"{type(exc).__name__}", "source": "Yahoo Finance"}
            data = {key: info.get(key) for key in FUNDAMENTAL_KEYS}
            missing = [key for key, value in data.items() if value is None]
            return {"status": "ok" if len(missing) < len(FUNDAMENTAL_KEYS) else "unavailable", "values": data, "missing": missing,
                    "source": "Yahoo Finance (vendor-reported, may lag filings)", "fetched_at": now_ist().isoformat()}

        return self.cache.get_or_set(("fundamentals", symbol), 6 * 3600, load)

    def _benchmark(self) -> pd.Series | None:
        try:
            return self.provider.get_ohlcv("NIFTY", "1D", 400)["close"]
        except DataUnavailable:
            return None

    def analyze(self, symbol: str) -> dict:
        if self.registry.is_index(symbol):
            raise ValueError(f"{symbol} is an index; use the Market Overview / Dashboard")
        daily = self.provider.get_ohlcv(symbol, "1D", 400)
        cfg = self.settings().signal
        metrics = compute_stock_metrics(daily, self._benchmark(), cfg)
        fundamentals = self.fundamentals(symbol)
        score = score_stock(metrics, fundamentals.get("values") if fundamentals.get("status") == "ok" else None)
        result = {
            "symbol": symbol,
            "meta": self.registry.meta(symbol).to_dict(),
            "quote": self.analysis.quote(symbol),
            "metrics": metrics,
            "score": score,
            "fundamentals": fundamentals,
            "daily_source": daily.attrs.get("provider"),
            "presets_matched": [key for key, (_, _, predicate) in PRESETS.items() if not metrics.get("insufficient") and predicate(metrics)],
        }
        for timeframe in ("1D", "1h"):
            try:
                snap = self.analysis.snapshot(symbol, timeframe, include_options=False)
                result[f"signal_{timeframe}"] = {"signal": snap["signal"], "regime": snap["regime"], "levels": snap["levels"],
                                                 "events": snap["events"], "technical": snap["technical"]}
            except DataUnavailable as exc:
                result[f"signal_{timeframe}"] = exc.to_dict()
        try:
            beta = beta_stats(daily["close"], self.provider.get_ohlcv("NIFTY", "1D", 400)["close"])
        except DataUnavailable:
            beta = None
        result["beta_vs_nifty"] = beta
        return result

    def universe(self, name: str) -> list[str]:
        if name == "WATCHLIST":
            return [s for s in self.settings().watchlist if not self.registry.is_index(s)]
        if name == "FNO":
            return self.registry.fno_stocks()
        if name in ("NIFTY 50", "NIFTY 100", "NIFTY NEXT 50"):
            return [row["symbol"] for row in self.registry.constituents(name)]
        raise ValueError(f"universe must be one of {UNIVERSES}")

    def scan(self, universe: str, preset: str | None, limit: int = 50) -> dict:
        symbols = self.universe(universe)
        if not symbols:
            raise DataUnavailable(f"{universe} universe", "no symbols in this universe")
        cfg = self.settings().signal
        frames = self.provider.get_ohlcv_batch(symbols, "1D", 400)
        bench = self._benchmark()
        metrics, unavailable = {}, []
        for symbol, frame in frames.items():
            if isinstance(frame, DataUnavailable):
                unavailable.append({"symbol": symbol, "reason": frame.reason})
                continue
            metrics[symbol] = compute_stock_metrics(frame, bench, cfg)
        matched = run_preset(metrics, preset) if preset else [s for s, m in metrics.items() if not m.get("insufficient")]
        rows = []
        for symbol in matched:
            m = metrics[symbol]
            score = score_stock(m, None)
            rows.append({
                "symbol": symbol, "close": m["close"], "change_pct": m["change_pct"], "ret_20d": m["ret_20d"], "rs_20": m.get("rs_20"),
                "rsi": m["rsi"], "adx": m["adx"], "vol_ratio": m["vol_ratio"], "atr_pct": m["atr_pct"],
                "dist_52w_high_pct": m["dist_52w_high_pct"], "avg_traded_value_cr": m["avg_traded_value_cr"],
                "technical_score": score["total"], "rating": score["rating"], "last_date": m["last_date"],
            })
        rows.sort(key=lambda r: -(r["technical_score"] or 0))
        return {
            "universe": universe, "preset": preset, "preset_definition": PRESETS[preset][1] if preset else None,
            "scanned": len(metrics), "matched": len(rows), "results": rows[:limit], "unavailable": unavailable,
            "note": "Technical score excludes fundamentals in scans; open Stock Analysis for the full score.",
            "generated_at": now_ist().isoformat(),
        }

    def hedge(self, request: HedgeRequest) -> dict:
        index = request.hedge_index
        index_daily = self.provider.get_ohlcv(index, "1D", 400)
        index_quote = self.provider.get_quote(index)
        symbols = [p.symbol for p in request.positions]
        frames = self.provider.get_ohlcv_batch(symbols, "1D", 400)
        quotes = self.provider.get_quotes(symbols)
        positions = []
        for p in request.positions:
            quote = quotes.get(p.symbol)
            frame = frames.get(p.symbol)
            if isinstance(quote, DataUnavailable) or quote is None:
                raise DataUnavailable(f"{p.symbol} price", getattr(quote, "reason", "no quote"), self.provider.label)
            beta = None if isinstance(frame, DataUnavailable) or frame is None else beta_stats(frame["close"], index_daily["close"])
            positions.append({"symbol": p.symbol, "kind": p.kind, "quantity": p.quantity, "avg_price": p.avg_price,
                              "price": quote.price, "price_time": quote.timestamp.isoformat(),
                              "beta": beta["beta"] if beta else None, "beta_detail": beta})
        chain_summary = None
        with contextlib.suppress(DataUnavailable):
            chain_summary = self._hedge_chain(index, self.settings().options.hedge_min_days_to_expiry)
        plan = hedge_plan(positions, index, index_quote.price, self.registry.meta(index).lot_size, chain_summary,
                          request.put_moneyness, request.call_moneyness)
        plan["generated_at"] = now_ist().isoformat()
        return plan

    def _hedge_chain(self, index: str, min_days: int) -> dict:
        expiries = self.options.expiries(index)
        today = now_ist().date()
        expiry = next((e for e in expiries if (e - today).days >= min_days), expiries[-1])
        chain = self.options.chain(index, expiry.isoformat())
        # protective puts sit 3–10% below spot: analyse a wider strike window than the default table
        wide = self.settings().options.model_copy(update={"strikes_around_atm": 60})
        return analyze_chain(chain, now_ist(), wide, None, self.analysis.market_status().is_trading)
