"""Market monitor loop: refreshes snapshots, detects new events, runs alerts/commentary/signals and
pushes updates to the dashboard. Blocking provider work runs in worker threads."""

from __future__ import annotations

import asyncio
import contextlib
import time
import traceback
from collections.abc import Callable

from ..analysis.options import signal_input
from ..config import RuntimeSettings
from ..data.models import DataUnavailable, now_ist
from .bus import EventBus
from .timeline import Timeline


class MonitorService:
    def __init__(self, analysis, options, commentary, alerts, signals, timeline: Timeline, bus: EventBus,
                 settings: Callable[[], RuntimeSettings]):
        self.analysis = analysis
        self.options = options
        self.commentary = commentary
        self.alerts = alerts
        self.signals = signals
        self.timeline = timeline
        self.bus = bus
        self.settings = settings
        self._wake: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._seen: dict[tuple[str, str], tuple[str, set[str]]] = {}
        self._last_option_poll: dict[str, float] = {}
        self._last_options: dict[str, dict] = {}
        self._last_eval = 0.0
        self._last_market_session: str | None = None
        self.state: dict = {"running": False, "cycles": 0, "last_cycle_at": None, "cycle_seconds": None, "interval": None,
                            "symbol_errors": {}, "last_error": None}

    def status(self) -> dict:
        return dict(self.state)

    def trigger(self) -> None:
        if self._loop and self._wake:
            self._loop.call_soon_threadsafe(self._wake.set)

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self.state["running"] = True
        try:
            while True:
                started = time.perf_counter()
                interval: float = self.settings().monitor.poll_seconds_closed
                try:
                    interval = await self._cycle()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — the loop must survive any single failure
                    self.state["last_error"] = f"{type(exc).__name__}: {exc}"
                    self.timeline.error("monitor", f"monitor cycle failed: {exc}", traceback.format_exc())
                self.state.update(cycles=self.state["cycles"] + 1, last_cycle_at=now_ist().isoformat(),
                                  cycle_seconds=round(time.perf_counter() - started, 2), interval=interval)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=interval)
                self._wake.clear()
        finally:
            self.state["running"] = False

    def _new_events(self, snap: dict) -> list[dict]:
        key = (snap["symbol"], snap["timeframe"])
        bar, seen = self._seen.get(key, (None, set()))
        if bar != snap["bar_time"]:
            seen = set()
        fresh = [event for event in snap["events"] if event["key"] not in seen]
        self._seen[key] = (snap["bar_time"], seen | {event["key"] for event in snap["events"]})
        return fresh if bar is not None else []

    def _post_process(self, snap: dict) -> None:
        self.alerts.check(snap)
        self.commentary.process(snap)
        if snap["market"]["is_trading"]:
            self.signals.record(snap)

    async def _cycle(self) -> float:
        settings = self.settings()
        market = await asyncio.to_thread(self.analysis.market_status)
        self.bus.publish("market_status", market.to_dict())
        if market.session != self._last_market_session:
            if self._last_market_session is not None:
                self.timeline.add("market", f"Market session: {market.label} ({market.reason})")
            self._last_market_session = market.session
        timeframe = settings.monitor.timeframe
        for symbol in settings.monitor.symbols:
            try:
                snap = await asyncio.to_thread(self.analysis.snapshot, symbol, timeframe, market=market)
            except DataUnavailable as exc:
                self.state["symbol_errors"][symbol] = exc.to_dict()
                self.bus.publish("market_update", {"symbol": symbol, "timeframe": timeframe, "unavailable": exc.to_dict()})
                continue
            self.state["symbol_errors"].pop(symbol, None)
            snap["new_events"] = self._new_events(snap)
            await asyncio.to_thread(self._post_process, snap)
            self.bus.publish("market_update", snap)

        now = time.time()
        for symbol in settings.monitor.option_symbols:
            if now - self._last_option_poll.get(symbol, 0) < settings.monitor.option_poll_seconds:
                continue
            self._last_option_poll[symbol] = now
            try:
                summary = await asyncio.to_thread(self.options.summary, symbol)
            except DataUnavailable as exc:
                self.bus.publish("options_update", {"symbol": symbol, "unavailable": exc.to_dict()})
                continue
            await asyncio.to_thread(self._option_events, symbol, summary, settings, market.is_trading)
            self.bus.publish("options_update", {k: v for k, v in summary.items() if k != "table"})

        if market.is_trading and now - self._last_eval > 300:
            self._last_eval = now
            await asyncio.to_thread(self.signals.evaluate_open)
        return settings.monitor.poll_seconds_open if market.is_trading else settings.monitor.poll_seconds_closed

    def _option_events(self, symbol: str, summary: dict, settings: RuntimeSettings, is_trading: bool) -> None:
        previous = self._last_options.get(symbol)
        self._last_options[symbol] = summary
        if not previous or previous["expiry"] != summary["expiry"] or previous["timestamp"] == summary["timestamp"]:
            return
        events = []
        threshold = settings.monitor.oi_change_event_pct
        for side, label, direction in (("call_oi", "Call", -1), ("put_oi", "Put", 1)):
            before, after = previous["totals"][side], summary["totals"][side]
            if before and abs(after - before) / before * 100 >= threshold:
                change = (after - before) / before * 100
                events.append({"key": f"oi_shift_{side}", "kind": "oi_shift", "direction": direction if change > 0 else -direction,
                               "priority": "MEDIUM", "message": f"{label} open interest changed {change:+.1f}% since the last poll", "bar_time": summary["timestamp"]})
        for wall, label in (("call_wall", "Highest call OI"), ("put_wall", "Highest put OI")):
            if previous[wall] != summary[wall] and summary[wall] is not None:
                events.append({"key": f"{wall}_shift", "kind": "oi_shift", "direction": 0, "priority": "MEDIUM",
                               "message": f"{label} strike moved from {previous[wall]} to {summary[wall]}", "bar_time": summary["timestamp"]})
        if not events:
            return
        for event in events:
            self.timeline.add("options", f"{symbol}: {event['message']}", symbol)
        self.alerts.check({"symbol": symbol, "timeframe": "options", "price": summary["spot"], "new_events": events,
                           "options": signal_input(summary), "signal": None, "regime": None})
