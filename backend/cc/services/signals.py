"""Signal history: records engine setups and tracks their outcomes against later bars."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd

from ..analysis.backtest import evaluate_signal_outcome
from ..analysis.signal_engine import LABEL_BEAR, LABEL_BULL, LABEL_HIGH_RISK
from ..data.models import DataUnavailable, now_ist
from ..storage.db import Database, dumps, loads
from .bus import EventBus
from .timeline import Timeline

SETUP_LABELS = {LABEL_BULL, LABEL_BEAR, LABEL_HIGH_RISK}
CLOSED = {"stopped", "target2", "target1_then_stop", "expired", "expired_after_target1", "not_triggered"}


class SignalService:
    def __init__(self, db: Database, analysis, timeline: Timeline, bus: EventBus):
        self.db = db
        self.analysis = analysis
        self.timeline = timeline
        self.bus = bus

    def record(self, snap: dict, source: str = "engine") -> dict | None:
        signal = snap["signal"]
        plan = signal.get("plan")
        if signal["label"] not in SETUP_LABELS or not plan or snap.get("mode") != "live":
            return None
        open_same = self.db.query_one(
            "SELECT id FROM signals WHERE symbol = ? AND timeframe = ? AND direction = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (snap["symbol"], snap["timeframe"], plan["direction"]),
        )
        if open_same:
            return None
        row = {
            "created_at": now_ist().isoformat(), "source": source, "symbol": snap["symbol"], "timeframe": snap["timeframe"],
            "bar_time": snap["bar_time"], "label": signal["label"], "direction": plan["direction"], "price": signal["price"],
            "bullish_pct": signal["bullish_pct"], "confidence": signal["model_confidence"], "coverage": signal["coverage"],
            "entry_low": plan["entry_low"], "entry_high": plan["entry_high"], "stop": plan["stop"], "target1": plan["target1"],
            "target2": plan["target2"], "rr": plan["risk_reward"],
        }
        row["id"] = self.db.execute(
            f"INSERT INTO signals({', '.join(row)}, payload) VALUES ({', '.join('?' for _ in row)}, ?)",
            (*row.values(), dumps(signal)),
        )
        self.timeline.add("signal", f"{row['symbol']} {row['timeframe']}: {row['label']} at {row['price']:,.2f} "
                                    f"(confidence {row['confidence']}%, R:R 1:{row['rr']})", row["symbol"], {"signal_id": row["id"]})
        self.bus.publish("signal", row)
        return row

    def list(self, limit: int = 200, symbol: str | None = None, status: str | None = None) -> list[dict]:
        clauses, params = [], []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.query(f"SELECT * FROM signals {where} ORDER BY id DESC LIMIT ?", (*params, limit))
        for row in rows:
            row["payload"], row["outcome"] = loads(row["payload"]), loads(row["outcome"])
        return rows

    def evaluate_open(self) -> int:
        rows = self.db.query("SELECT * FROM signals WHERE status = 'open'")
        groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for row in rows:
            groups[(row["symbol"], row["timeframe"])].append(row)
        closed = 0
        for (symbol, timeframe), items in groups.items():
            try:
                frame = self.analysis.frame(symbol, timeframe, 1000)
            except DataUnavailable:
                continue
            for row in items:
                after = frame[frame.index > pd.Timestamp(row["bar_time"])]
                outcome = evaluate_signal_outcome(row, after)
                if outcome["status"] in CLOSED:
                    self.db.execute("UPDATE signals SET status = 'closed', outcome = ?, closed_at = ? WHERE id = ?",
                                    (dumps(outcome), now_ist().isoformat(), row["id"]))
                    closed += 1
                    self.timeline.add("signal", f"Signal #{row['id']} {symbol} {timeframe} closed: {outcome['status']}"
                                      + (f" ({outcome['r_multiple']:+.2f}R)" if "r_multiple" in outcome else ""), symbol)
                elif datetime.fromisoformat(row["created_at"]) < now_ist() - timedelta(days=10):
                    self.db.execute("UPDATE signals SET status = 'closed', outcome = ?, closed_at = ? WHERE id = ?",
                                    (dumps({**outcome, "status": "expired"}), now_ist().isoformat(), row["id"]))
                    closed += 1
                else:
                    self.db.execute("UPDATE signals SET outcome = ? WHERE id = ?", (dumps(outcome), row["id"]))
        return closed

    def stats(self) -> dict:
        rows = self.list(5000)
        by_label: dict[str, dict] = {}
        for row in rows:
            entry = by_label.setdefault(row["label"], {"signals": 0, "open": 0, "closed": 0, "not_triggered": 0, "wins": 0, "r": []})
            entry["signals"] += 1
            if row["status"] == "open":
                entry["open"] += 1
                continue
            entry["closed"] += 1
            outcome = row["outcome"] or {}
            if outcome.get("status") == "not_triggered":
                entry["not_triggered"] += 1
            elif "r_multiple" in outcome:
                entry["r"].append(outcome["r_multiple"])
                entry["wins"] += outcome["r_multiple"] > 0
        summary = {}
        for label, e in by_label.items():
            r = e.pop("r")
            summary[label] = {**e, "win_rate": round(e["wins"] / len(r) * 100, 1) if r else None,
                              "avg_r": round(sum(r) / len(r), 3) if r else None, "evaluated": len(r)}
        return {"by_label": summary, "total": len(rows), "note": "Outcomes use later bars from the same provider; stop assumed first on ambiguous bars."}
