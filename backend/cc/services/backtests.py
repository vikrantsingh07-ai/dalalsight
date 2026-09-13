"""Backtest jobs (one at a time, persisted)."""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable

from ..analysis.backtest import BacktestParams, run_backtest
from ..config import TIMEFRAME_MINUTES, RuntimeSettings
from ..data.models import now_ist
from ..storage.db import Database, dumps, loads
from .bus import EventBus
from .timeline import Timeline


class BacktestService:
    def __init__(self, db: Database, analysis, settings: Callable[[], RuntimeSettings], timeline: Timeline, bus: EventBus):
        self.db = db
        self.analysis = analysis
        self.settings = settings
        self.timeline = timeline
        self.bus = bus
        self._lock = threading.Lock()

    def start(self, params: BacktestParams) -> int:
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("a backtest is already running")
        try:
            job_id = self.db.execute("INSERT INTO backtests(created_at, status, params) VALUES (?, 'running', ?)",
                                     (now_ist().isoformat(), dumps(params.model_dump())))
        except Exception:
            self._lock.release()
            raise
        threading.Thread(target=self._run, args=(job_id, params), daemon=True).start()
        return job_id

    def _run(self, job_id: int, params: BacktestParams) -> None:
        try:
            frame = self.analysis.frame(params.symbol, params.timeframe, params.bars)
            intraday = TIMEFRAME_MINUTES[params.timeframe] < 1440
            result = run_backtest(frame, params, self.settings(), intraday,
                                  progress=lambda p: self.bus.publish("backtest_progress", {"id": job_id, "progress": round(p * 100, 1)}))
            result["summary"]["data_source"] = frame.attrs.get("provider")
            self.db.execute("UPDATE backtests SET status = 'completed', summary = ?, trades = ? WHERE id = ?",
                            (dumps(result["summary"]), dumps(result["trades"]), job_id))
            s = result["summary"]
            self.timeline.add("backtest", f"Backtest #{job_id} {params.symbol} {params.timeframe}: {s['trades']} trades, "
                                          f"win rate {s['win_rate']}%, expectancy {s['expectancy_r']}R", params.symbol)
        except Exception as exc:  # noqa: BLE001
            self.db.execute("UPDATE backtests SET status = 'failed', error = ? WHERE id = ?", (f"{type(exc).__name__}: {exc}"[:500], job_id))
            self.timeline.error("backtest", f"Backtest #{job_id} failed: {exc}", traceback.format_exc())
        finally:
            self._lock.release()
            self.bus.publish("backtest_done", {"id": job_id})

    def get(self, job_id: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM backtests WHERE id = ?", (job_id,))
        if row:
            row["params"], row["summary"], row["trades"] = loads(row["params"]), loads(row["summary"]), loads(row["trades"])
        return row

    def list(self, limit: int = 50) -> list[dict]:
        rows = self.db.query("SELECT id, created_at, status, params, summary, error FROM backtests ORDER BY id DESC LIMIT ?", (limit,))
        for row in rows:
            row["params"], row["summary"] = loads(row["params"]), loads(row["summary"])
            if row["summary"]:
                row["summary"].pop("equity_curve_r", None)
        return rows
