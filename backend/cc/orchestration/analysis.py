"""Analysis orchestration: provider data → indicators, levels, events, regime, signal, options.

Signals and events use completed bars only: during the session the forming bar is excluded
from analysis (its price is still shown as the live price).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from ..analysis.events import detect_events, technical_state
from ..analysis.indicators import compute_indicators
from ..analysis.levels import compute_levels
from ..analysis.options import analyze_chain, recommend_contracts, signal_input, years_to_expiry
from ..analysis.regime import detect_regime
from ..analysis.signal_engine import LABEL_BEAR, LABEL_BULL, LABEL_HIGH_RISK, build_signal
from ..analysis.strategies import (
    TEMPLATES,
    build_template,
    evaluate_strategy,
    iv_regime,
    price_leg,
    suggest_strategies,
)
from ..config import TIMEFRAME_MINUTES, RuntimeSettings
from ..data.cache import TTLCache
from ..data.market_hours import market_status as local_market_status
from ..data.models import DataUnavailable, MarketStatus, OptionChain, now_ist
from ..data.provider import MarketDataProvider
from ..data.symbols import SymbolRegistry
from ..storage.db import Database, dumps, loads

IST_OFFSET_SECONDS = 19800


def _clean(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 4) if np.isfinite(number) else None


class AnalysisService:
    def __init__(self, provider: MarketDataProvider, registry: SymbolRegistry, settings: Callable[[], RuntimeSettings],
                 cache: TTLCache, db: Database):
        self.provider = provider
        self.registry = registry
        self.settings = settings
        self.cache = cache
        self.db = db
        self.options: OptionsService | None = None
        self.latest: dict[tuple[str, str], dict] = {}
        # signal history per (symbol, timeframe, settings): bar time -> engine signal at that bar's close
        self._history: dict[tuple, dict[str, dict]] = {}
        self._history_lock = threading.Lock()

    def market_status(self) -> MarketStatus:
        try:
            return self.provider.get_market_status()
        except DataUnavailable:
            status = local_market_status(now_ist(), self.settings().market_hours, set())
            status.reason += " (exchange status unavailable; local calendar)"
            return status

    def quote(self, symbol: str) -> dict:
        try:
            return self.provider.get_quote(symbol).to_dict()
        except DataUnavailable as exc:
            return exc.to_dict()

    def frame(self, symbol: str, timeframe: str, bars: int = 600) -> pd.DataFrame:
        if timeframe not in TIMEFRAME_MINUTES:
            raise ValueError(f"unsupported timeframe {timeframe}")
        return self.provider.get_ohlcv(symbol, timeframe, bars)

    @staticmethod
    def _forming(last: pd.Timestamp, timeframe: str, now: datetime) -> bool:
        minutes = TIMEFRAME_MINUTES[timeframe]
        if timeframe == "1D":
            return last.date() == now.date()
        if timeframe == "1W":
            return last + pd.Timedelta(days=7) > now
        return last + pd.Timedelta(minutes=minutes) > now

    def snapshot(self, symbol: str, timeframe: str, *, frame: pd.DataFrame | None = None, market: MarketStatus | None = None,
                 mode: str = "live", include_options: bool = True) -> dict:
        settings = self.settings()
        cfg = settings.signal
        market = market or self.market_status()
        raw = frame if frame is not None else self.frame(symbol, timeframe, 600)
        intraday = TIMEFRAME_MINUTES[timeframe] < 1440
        forming = mode == "live" and market.is_trading and len(raw) > 1 and self._forming(raw.index[-1], timeframe, now_ist())
        completed = raw.iloc[:-1] if forming else raw
        completed.attrs = dict(raw.attrs)
        if len(completed) < 30:
            raise DataUnavailable(f"{symbol} {timeframe} analysis", f"only {len(completed)} completed bars", raw.attrs.get("provider", ""))
        ind = compute_indicators(completed, cfg, intraday)

        options_summary, options_status = None, None
        meta = self.registry.meta(symbol)
        if include_options and meta.option_type and self.options is not None:
            try:
                options_summary = self.options.summary(symbol)
            except DataUnavailable as exc:
                options_status = exc.to_dict()
        elif include_options:
            options_status = {"status": "unavailable", "reason": "instrument has no NSE-listed options"}
        opt_input = signal_input(options_summary) if options_summary else None

        levels = compute_levels(ind, intraday, cfg.swing_lookback, cfg.breakout_lookback, opt_input)
        events = detect_events(ind, levels, cfg, settings.commentary.level_test_atr)
        quote = self.quote(symbol) if mode == "live" else None
        breadth = None
        extra = (quote or {}).get("extra") or {}
        if extra.get("advances") is not None:
            breadth = {"advances": extra["advances"], "declines": extra.get("declines")}
        regime = detect_regime(ind, breadth)
        sources = [raw.attrs.get("provider", "unknown")]
        if options_summary:
            sources.append(options_summary["provider"])
        signal = build_signal(symbol, timeframe, ind, events, levels, regime, opt_input, cfg, settings.risk, sources)
        price = float(raw["close"].iloc[-1]) if mode == "live" else float(completed["close"].iloc[-1])
        snap = {
            "symbol": symbol,
            "timeframe": timeframe,
            "mode": mode,
            "generated_at": now_ist().isoformat(),
            "market": market.to_dict(),
            "meta": meta.to_dict(),
            "quote": quote,
            "price": price,
            "bar_time": ind.index[-1].isoformat(),
            "forming_bar_excluded": bool(forming),
            "provenance": {
                "provider": raw.attrs.get("provider"),
                "has_volume": bool(ind.attrs.get("has_volume")),
                "stale": bool(raw.attrs.get("stale", False)),
                "lag_seconds": raw.attrs.get("lag_seconds"),
                "bars": len(ind),
                "first_bar": ind.index[0].isoformat(),
                "last_bar": raw.index[-1].isoformat(),
                "fetched_at": raw.attrs.get("fetched_at"),
                "live_ticks_merged": bool(raw.attrs.get("live_ticks_merged", False)),
            },
            "signal": signal.to_dict(),
            "regime": regime.to_dict(),
            "levels": levels.to_dict(),
            "events": [event.to_dict() for event in events],
            "technical": technical_state(ind, cfg),
            "options": None if not options_summary or opt_input is None else {
                **opt_input, "expiry": options_summary["expiry"], "max_pain": options_summary["max_pain"],
                "atm_iv": options_summary["atm_iv"], "expected_range": options_summary["expected_range"],
                "timestamp": options_summary["timestamp"],
            },
            "options_status": options_status,
        }
        if mode == "live":
            self.latest[(symbol, timeframe)] = snap
        return snap

    HISTORY_WINDOW = 300  # trailing bars used to judge each historical bar, as in the backtest
    HISTORY_WARMUP = 120
    MARKER_GAP = 6  # bars: a same-direction setup restarting sooner than this is not a new marker

    def signal_history(self, symbol: str, timeframe: str, bars: int = 250) -> dict:
        """The engine's signal at each of the last ``bars`` completed bars, for BUY/SELL markers on the chart.

        Each bar is judged on a trailing window ending at that bar (as in the backtest), so a marker shows what the engine
        would have said at that candle's close. Results are cached per bar and only new bars are computed. Option data is
        excluded because there are no historical option chains.
        """
        settings = self.settings()
        cfg = settings.signal
        market = self.market_status()
        raw = self.frame(symbol, timeframe, 600)
        forming = market.is_trading and len(raw) > 1 and self._forming(raw.index[-1], timeframe, now_ist())
        completed = raw.iloc[:-1] if forming else raw
        completed.attrs = dict(raw.attrs)
        intraday = TIMEFRAME_MINUTES[timeframe] < 1440
        ind = compute_indicators(completed, cfg, intraday)
        if len(ind) <= self.HISTORY_WARMUP:
            raise DataUnavailable(f"{symbol} {timeframe} signal history", f"only {len(ind)} completed bars", raw.attrs.get("provider", ""))
        key = (symbol, timeframe, cfg.model_dump_json(), settings.risk.model_dump_json(), settings.commentary.level_test_atr)
        with self._history_lock:
            cache = self._history.pop(key, {})
            self._history[key] = cache  # most recently used last
            while len(self._history) > 24:
                self._history.pop(next(iter(self._history)))
        rows: list[dict] = []
        for i in range(max(self.HISTORY_WARMUP, len(ind) - bars), len(ind)):
            stamp = ind.index[i].isoformat()
            entry = cache.get(stamp)
            if entry is None:
                window = ind.iloc[max(0, i - self.HISTORY_WINDOW + 1): i + 1]
                levels = compute_levels(window, intraday, cfg.swing_lookback, cfg.breakout_lookback)
                events = detect_events(window, levels, cfg, settings.commentary.level_test_atr)
                signal = build_signal(symbol, timeframe, window, events, levels, detect_regime(window), None, cfg, settings.risk, ["history"])
                entry = {"bar_time": stamp, "label": signal.label, "direction": signal.direction, "bullish_pct": signal.bullish_pct,
                         "confidence": signal.model_confidence, "price": signal.price}
                cache[stamp] = entry
            rows.append(entry)
        current = {row["bar_time"] for row in rows}
        for stamp in [s for s in list(cache) if s not in current]:
            cache.pop(stamp, None)

        # One marker where a run of setups in one direction begins (BUY up, SELL down); risky = HIGH-RISK at that bar.
        # A run that restarts within MARKER_GAP bars of the last setup in the same direction counts as the same signal,
        # so brief interruptions don't stack arrows on top of each other.
        markers: list[dict] = []
        previous = 0
        last_setup = {1: -self.MARKER_GAP - 1, -1: -self.MARKER_GAP - 1}
        for index, row in enumerate(rows):
            side = row["direction"] if row["label"] in (LABEL_BULL, LABEL_BEAR, LABEL_HIGH_RISK) else 0
            if side and side != previous and index - last_setup[side] > self.MARKER_GAP:
                seconds = int(pd.Timestamp(row["bar_time"]).timestamp()) + IST_OFFSET_SECONDS
                markers.append({**row, "time": seconds, "side": "BUY" if side > 0 else "SELL", "risky": row["label"] == LABEL_HIGH_RISK})
            if side:
                last_setup[side] = index
            previous = side
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["label"]] = counts.get(row["label"], 0) + 1
        return {
            "symbol": symbol, "timeframe": timeframe, "bars": len(rows), "markers": markers, "latest": rows[-1], "counts": counts,
            "time_basis": "IST wall-clock seconds (UTC epoch + 19800)",
            "note": "Rebuilt at each candle close from the bars available then (no look-ahead); options data excluded.",
        }

    def chart(self, symbol: str, timeframe: str, bars: int = 500) -> dict:
        raw = self.frame(symbol, timeframe, max(bars, 300))
        cfg = self.settings().signal
        intraday = TIMEFRAME_MINUTES[timeframe] < 1440
        ind = compute_indicators(raw, cfg, intraday)
        view = ind.tail(bars)
        # explicit unit: pandas 3 indexes may be stored in s/ms/us, so raw asi8 is not always nanoseconds
        times = view.index.as_unit("s").asi8 + IST_OFFSET_SECONDS
        candles = [
            {"time": int(t), "open": _clean(o), "high": _clean(h), "low": _clean(low), "close": _clean(c), "volume": _clean(v)}
            for t, o, h, low, c, v in zip(times, view["open"], view["high"], view["low"], view["close"], view["volume"], strict=False)
        ]

        def series(column: str) -> list[dict]:
            return [{"time": int(t), "value": _clean(v)} for t, v in zip(times, view[column], strict=False) if _clean(v) is not None]

        columns = ["ema_fast", "ema_slow", "ema20", "ema50", "sma200", "vwap", "bb_upper", "bb_lower", "supertrend", "rsi",
                   "macd", "macd_signal", "macd_hist"]
        levels = compute_levels(ind, intraday, cfg.swing_lookback, cfg.breakout_lookback).to_dict()
        first = view.index[0].isoformat()
        markers = []
        for row in self.db.query("SELECT id, bar_time, label, direction, price FROM signals WHERE symbol = ? AND timeframe = ? AND bar_time >= ? ORDER BY id",
                                 (symbol, timeframe, first)):
            ts = int(pd.Timestamp(row["bar_time"]).timestamp()) + IST_OFFSET_SECONDS
            markers.append({"time": ts, "label": row["label"], "direction": row["direction"], "price": row["price"], "id": row["id"]})
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "candles": candles,
            "indicators": {column: series(column) for column in columns},
            "periods": {"ema_fast": cfg.ema_fast, "ema_slow": cfg.ema_slow},
            "levels": levels,
            "markers": markers,
            "time_basis": "IST wall-clock seconds (UTC epoch + 19800)",
            "provenance": {"provider": raw.attrs.get("provider"), "has_volume": bool(ind.attrs.get("has_volume")),
                           "stale": bool(raw.attrs.get("stale", False)), "lag_seconds": raw.attrs.get("lag_seconds"),
                           "bars": len(view), "last_bar": raw.index[-1].isoformat(), "fetched_at": raw.attrs.get("fetched_at")},
        }


class OptionsService:
    def __init__(self, provider: MarketDataProvider, registry: SymbolRegistry, settings: Callable[[], RuntimeSettings],
                 cache: TTLCache, db: Database, analysis: AnalysisService):
        self.provider = provider
        self.registry = registry
        self.settings = settings
        self.cache = cache
        self.db = db
        self.analysis = analysis
        analysis.options = self

    def expiries(self, symbol: str) -> list[date]:
        return self.provider.get_expiries(symbol)

    def resolve_expiry(self, symbol: str, expiry: str | None) -> date:
        expiries = self.expiries(symbol)
        if not expiry:
            return expiries[0]
        try:
            wanted = date.fromisoformat(expiry)
        except ValueError as exc:
            raise ValueError("expiry must be YYYY-MM-DD") from exc
        if wanted not in expiries:
            raise ValueError(f"{expiry} is not a listed expiry for {symbol}")
        return wanted

    def chain(self, symbol: str, expiry: str | None = None) -> OptionChain:
        chain = self.provider.get_option_chain(symbol, self.resolve_expiry(symbol, expiry))
        if chain.lot_size is None:
            chain.lot_size = self.registry.meta(symbol).lot_size
        return chain

    def iv_history(self, symbol: str) -> list[float]:
        rows = self.db.query("SELECT ts, summary FROM option_snapshots WHERE symbol = ? ORDER BY id DESC LIMIT 2000", (symbol,))
        today = now_ist().date().isoformat()
        by_day: dict[str, float] = {}
        for row in rows:
            summary = loads(row["summary"])
            day = str(summary.get("timestamp", row["ts"]))[:10]
            if day != today and day not in by_day and summary.get("atm_iv") is not None:
                by_day[day] = summary["atm_iv"]
        return list(by_day.values())

    def summary(self, symbol: str, expiry: str | None = None) -> dict:
        market = self.analysis.market_status()
        ttl = self.settings().monitor.option_poll_seconds if market.is_trading else 900
        expiry_date = self.resolve_expiry(symbol, expiry)

        def load() -> dict:
            chain = self.chain(symbol, expiry_date.isoformat())
            result = analyze_chain(chain, now_ist(), self.settings().options, self.iv_history(symbol), market.is_trading)
            self._store(result)
            return result

        return self.cache.get_or_set(("option_summary", symbol, expiry_date), ttl, load)

    def _store(self, s: dict) -> None:
        exists = self.db.query_one("SELECT id FROM option_snapshots WHERE symbol = ? AND expiry = ? AND ts = ?",
                                   (s["symbol"], s["expiry"], s["timestamp"]))
        if exists:
            return
        compact = {k: s[k] for k in ("timestamp", "spot", "atm_strike", "atm_iv", "atm_straddle", "pcr_oi", "pcr_volume",
                                      "max_pain", "call_wall", "put_wall", "totals", "expected_move_1sd")}
        self.db.execute("INSERT INTO option_snapshots(ts, symbol, expiry, summary) VALUES (?, ?, ?, ?)",
                        (s["timestamp"], s["symbol"], s["expiry"], dumps(compact)))

    def recommendations(self, symbol: str, expiry: str | None, timeframe: str) -> dict:
        summary = self.summary(symbol, expiry)
        snap = self.analysis.snapshot(symbol, timeframe)
        signal = snap["signal"]
        risk = self.settings().risk
        risk_capital = risk.capital * risk.risk_per_trade_pct / 100
        tradable = signal["label"] in (LABEL_BULL, LABEL_BEAR, LABEL_HIGH_RISK)
        result = recommend_contracts(summary, signal["direction"] if tradable else 0, self.settings().options, risk_capital)
        return {
            "symbol": symbol, "expiry": summary["expiry"], "timeframe": timeframe,
            "signal": {k: signal[k] for k in ("label", "direction", "bullish_pct", "bearish_pct", "model_confidence", "plan", "reasons", "risks")},
            "spot": summary["spot"], "lot_size": summary["lot_size"], "risk_capital": risk_capital, **result,
        }

    def build_strategy(self, symbol: str, expiry: str | None, template: str | None, legs: list[dict] | None, lots: int,
                       width_steps: int | None) -> dict:
        chain = self.chain(symbol, expiry)
        now = now_ist()
        rate = self.settings().options.risk_free_rate
        years = years_to_expiry(chain.expiry, now)
        if template:
            built = build_template(template, chain, now, rate, lots, width_steps)
            name = TEMPLATES[template]["name"]
        elif legs:
            built = [price_leg(chain, leg["option_type"], leg["side"], leg["strike"], leg["lots"], years, rate) for leg in legs]
            name = "Custom strategy"
        else:
            raise ValueError("provide a template or legs")
        summary = self.summary(symbol, chain.expiry.isoformat())
        atm_iv = summary["atm_iv"] / 100 if summary["atm_iv"] else None
        result = evaluate_strategy(built, chain.spot, chain.lot_size or 0, years, rate, atm_iv, name)
        result.update({"symbol": symbol, "expiry": chain.expiry.isoformat(), "chain_timestamp": chain.timestamp.isoformat(),
                       "provider": chain.provider, "template": template})
        return result

    def suggest(self, symbol: str, expiry: str | None, timeframe: str) -> dict:
        summary = self.summary(symbol, expiry)
        snap = self.analysis.snapshot(symbol, timeframe)
        vix = None
        try:
            quote = self.provider.get_quote("INDIAVIX")
            vix = {"price": quote.price, "year_high": quote.extra.get("year_high"), "year_low": quote.extra.get("year_low")}
        except DataUnavailable:
            pass
        iv = iv_regime(summary["iv_percentile"], vix)
        suggestions = suggest_strategies(snap["signal"]["label"], snap["signal"]["direction"], snap["regime"]["code"], iv)
        evaluated = []
        for item in suggestions:
            try:
                evaluated.append({**item, "evaluation": self.build_strategy(symbol, summary["expiry"], item["key"], None, 1, None)})
            except (DataUnavailable, ValueError) as exc:
                evaluated.append({**item, "evaluation": None, "error": str(exc)})
        return {
            "symbol": symbol, "expiry": summary["expiry"], "timeframe": timeframe, "iv_context": iv,
            "signal_label": snap["signal"]["label"], "regime": snap["regime"]["label"],
            "suggestions": evaluated,
            "note": None if evaluated else "No strategy fits the current evidence: NO TRADE / WAIT FOR CONFIRMATION.",
        }


def session_dates(frame: pd.DataFrame) -> list[str]:
    return sorted({d.isoformat() for d in frame.index.date})


def recent_window(days: int) -> tuple[date, date]:
    end = now_ist().date()
    return end - timedelta(days=days), end
