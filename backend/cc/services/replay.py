"""Replay a recorded session bar by bar through the live analysis and commentary pipeline.

Everything produced is labelled REPLAY; option chains are excluded because historical chains are
not available from the public provider.
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from datetime import date

from ..config import RuntimeSettings
from ..data.models import MarketStatus, now_ist
from .bus import EventBus
from .timeline import Timeline


class ReplayService:
    def __init__(self, analysis, commentary, bus: EventBus, timeline: Timeline, settings: Callable[[], RuntimeSettings]):
        self.analysis = analysis
        self.commentary = commentary
        self.bus = bus
        self.timeline = timeline
        self.settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.state: dict = {"running": False}

    def status(self) -> dict:
        return dict(self.state)

    def start(self, symbol: str, timeframe: str, session_date: str | None, interval_seconds: float) -> dict:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("a replay is already running; stop it first")
        frame = self.analysis.frame(symbol, timeframe, 3000)
        dates = sorted(set(frame.index.date))
        target = date.fromisoformat(session_date) if session_date else dates[-1]
        if target not in dates:
            raise ValueError(f"no {timeframe} bars for {target}; available: {', '.join(d.isoformat() for d in dates[-10:])}")
        positions = [i for i, d in enumerate(frame.index.date) if d == target]
        if positions[0] < 60:
            raise ValueError("not enough warm-up bars before that session for indicators")
        self._stop.clear()
        self.commentary.reset("replay")
        self.state = {"running": True, "symbol": symbol, "timeframe": timeframe, "session_date": target.isoformat(),
                      "bars": len(positions), "processed": 0, "interval_seconds": interval_seconds, "started_at": now_ist().isoformat(),
                      "provider": frame.attrs.get("provider"), "available_dates": [d.isoformat() for d in dates[-10:]]}
        self._thread = threading.Thread(target=self._run, args=(frame, positions, symbol, timeframe, target, interval_seconds), daemon=True)
        self._thread.start()
        self.timeline.add("replay", f"REPLAY started: {symbol} {timeframe} session {target.isoformat()} ({len(positions)} bars)", symbol)
        return self.status()

    def stop(self) -> dict:
        self._stop.set()
        return self.status()

    def _run(self, frame, positions: list[int], symbol: str, timeframe: str, target: date, interval: float) -> None:
        market = MarketStatus(session="OPEN", is_trading=True, label="REPLAY (recorded session)", now=now_ist(), session_date=target,
                              next_open=None, reason=f"replay of recorded {timeframe} bars from {target.isoformat()}")
        try:
            for count, pos in enumerate(positions, start=1):
                if self._stop.is_set():
                    break
                sub = frame.iloc[: pos + 1]
                sub.attrs = dict(frame.attrs)
                snap = self.analysis.snapshot(symbol, timeframe, frame=sub, market=market, mode="replay", include_options=False)
                entry = self.commentary.process(snap, mode="replay")
                self.state["processed"] = count
                self.bus.publish("replay_update", {
                    "progress": round(count / len(positions) * 100, 1), "bar_time": snap["bar_time"], "price": snap["price"],
                    "symbol": symbol, "timeframe": timeframe, "signal": {k: snap["signal"][k] for k in ("label", "bullish_pct", "model_confidence", "plan")},
                    "regime": snap["regime"]["label"], "events": [e["message"] for e in snap["events"]], "commentary": entry,
                })
                if self._stop.wait(interval):
                    break
        except Exception as exc:  # noqa: BLE001
            self.state["error"] = f"{type(exc).__name__}: {exc}"
            self.timeline.error("replay", f"replay failed: {exc}", traceback.format_exc())
        finally:
            self.state["running"] = False
            self.state["finished_at"] = now_ist().isoformat()
            self.bus.publish("replay_update", {"finished": True, **self.state})
            self.timeline.add("replay", f"REPLAY finished: {symbol} {timeframe} ({self.state.get('processed', 0)} bars)", symbol)
