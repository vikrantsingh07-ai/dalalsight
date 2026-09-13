"""Event-driven market commentary.

Commentary is produced only on material change (regime or signal-label change, confidence moves,
confirmed crossovers, breakouts, level tests, volume spikes, sharp moves), with a global interval
and per-event cooldowns. HIGH/CRITICAL items may be narrated by the LLM; the narration is rejected
if it contains any number that is not in the facts, and the deterministic text is kept instead.
No automatic live commentary is produced while the market is closed.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ..config import PRIORITY_ORDER, RuntimeSettings
from ..data.models import now_ist
from ..services.bus import EventBus
from ..storage.db import Database, dumps, loads
from .llm import AIUnavailable, ModelManager, unverified_numbers


@dataclass
class _State:
    label: str | None = None
    regime: str | None = None
    confidence: float | None = None
    last_emit: float = 0.0
    event_times: dict[str, float] = field(default_factory=dict)
    last_bar: str | None = None


def _max_priority(items: list[tuple[str, str]]) -> str:
    return max((p for p, _ in items), key=lambda p: PRIORITY_ORDER[p], default="LOW")


class CommentaryEngine:
    def __init__(self, db: Database, models: ModelManager, bus: EventBus, settings: Callable[[], RuntimeSettings]):
        self.db = db
        self.models = models
        self.bus = bus
        self._settings = settings
        self._states: dict[tuple[str, str, str], _State] = {}
        self._lock = threading.Lock()
        self.clock: Callable[[], float] = time.time

    def process(self, snap: dict, mode: str = "live") -> dict | None:
        cfg = self._settings().commentary
        if not cfg.enabled:
            return None
        market = snap.get("market") or {}
        if mode == "live" and cfg.during_market_hours_only and not market.get("is_trading"):
            return None
        signal, regime = snap["signal"], snap["regime"]
        key = (mode, snap["symbol"], snap["timeframe"])
        now = self.clock()
        with self._lock:
            state = self._states.setdefault(key, _State())
            first = state.label is None
            changes: list[tuple[str, str]] = []
            if not first and regime["code"] != state.regime:
                priority = "HIGH" if regime["code"] in ("BREAKOUT", "STRONG_BULLISH_TREND", "STRONG_BEARISH_TREND", "HIGH_VOLATILITY") else "MEDIUM"
                changes.append((priority, f"Regime changed to {regime['label']}"))
            if not first and signal["label"] != state.label:
                setup = signal["label"] in ("BULLISH SETUP", "BEARISH SETUP", "HIGH-RISK SETUP")
                changes.append(("HIGH" if setup else "MEDIUM", f"Signal changed from {state.label} to {signal['label']}"))
            elif not first and state.confidence is not None and abs(signal["model_confidence"] - state.confidence) >= cfg.confidence_change_points:
                changes.append(("MEDIUM", f"Model confidence moved from {state.confidence:.1f}% to {signal['model_confidence']:.1f}%"))
            new_bar = snap.get("bar_time") != state.last_bar
            if new_bar:
                for event in snap.get("events") or []:
                    last = state.event_times.get(event["key"], 0.0)
                    if now - last >= cfg.event_cooldown_seconds:
                        changes.append((event["priority"], event["message"]))
                        state.event_times[event["key"]] = now
            state.label, state.regime, state.confidence = signal["label"], regime["code"], signal["model_confidence"]
            state.last_bar = snap.get("bar_time")
            if not changes:
                return None
            priority = _max_priority(changes)
            if PRIORITY_ORDER[priority] < PRIORITY_ORDER["HIGH"] and now - state.last_emit < cfg.min_interval_seconds:
                return None
            state.last_emit = now

        facts = self.facts(snap, [message for _, message in changes])
        text = self.deterministic_text(facts)
        speak = cfg.speak_min_priority and PRIORITY_ORDER[priority] >= PRIORITY_ORDER[cfg.speak_min_priority] and self._settings().voice.enabled
        entry = {
            "ts": now_ist().isoformat(), "symbol": snap["symbol"], "timeframe": snap["timeframe"], "priority": priority,
            "text": text, "text_source": "engine", "speak": bool(speak), "mode": mode, "facts": facts,
        }
        entry["id"] = self.db.execute(
            "INSERT INTO commentary(ts, symbol, timeframe, priority, text, text_source, speak, mode, payload) VALUES (?,?,?,?,?,?,?,?,?)",
            (entry["ts"], entry["symbol"], entry["timeframe"], priority, text, "engine", int(entry["speak"]), mode, dumps(facts)),
        )
        self.bus.publish("commentary", entry)
        if mode == "live" and PRIORITY_ORDER[priority] >= PRIORITY_ORDER[cfg.llm_min_priority]:
            threading.Thread(target=self._narrate, args=(entry,), daemon=True).start()
        return entry

    @staticmethod
    def facts(snap: dict, changes: list[str]) -> dict:
        signal, levels = snap["signal"], snap["levels"]
        support, resistance = levels.get("nearest_support"), levels.get("nearest_resistance")
        return {
            "symbol": snap["symbol"],
            "timeframe": snap["timeframe"],
            "bar_time": snap.get("bar_time"),
            "price": round(snap["price"], 2),
            "changes": changes,
            "signal_label": signal["label"],
            "bullish_scenario_pct": signal["bullish_pct"],
            "bearish_scenario_pct": signal["bearish_pct"],
            "model_confidence_pct": signal["model_confidence"],
            "regime": snap["regime"]["label"],
            "nearest_support": None if not support else {"price": support["price"], "label": support["label"]},
            "nearest_resistance": None if not resistance else {"price": resistance["price"], "label": resistance["label"]},
            "plan": signal.get("plan"),
            "unavailable": [c["name"] for c in signal["components"] if not c["available"]],
            "data_source": (snap.get("provenance") or {}).get("provider"),
        }

    @staticmethod
    def deterministic_text(f: dict) -> str:
        parts = [f"{f['symbol']} {f['timeframe']} at {f['price']:,.2f}: " + "; ".join(f["changes"]) + "."]
        parts.append(f"Signal {f['signal_label']} — bullish scenario {f['bullish_scenario_pct']}%, model confidence {f['model_confidence_pct']}%. Regime: {f['regime']}.")
        levels = []
        if f["nearest_support"]:
            levels.append(f"support {f['nearest_support']['price']:,.2f} ({f['nearest_support']['label']})")
        if f["nearest_resistance"]:
            levels.append(f"resistance {f['nearest_resistance']['price']:,.2f} ({f['nearest_resistance']['label']})")
        if levels:
            parts.append("Nearest " + ", ".join(levels) + ".")
        plan = f.get("plan")
        if plan and f["signal_label"] in ("BULLISH SETUP", "BEARISH SETUP", "HIGH-RISK SETUP", "LOW-QUALITY SETUP"):
            parts.append(f"Plan: entry {plan['entry_low']:,.2f}–{plan['entry_high']:,.2f}, stop {plan['stop']:,.2f}, T1 {plan['target1']:,.2f}, R:R 1:{plan['risk_reward']}.")
        return " ".join(parts)

    def _narrate(self, entry: dict) -> None:
        facts = entry["facts"]
        prompt = (
            "You are a concise Indian-markets trading-desk commentator. Write 2-3 sentences describing what just "
            "changed, the current setup and the key levels, using ONLY the facts JSON. Do not introduce any number "
            "that is not in the facts. Do not tell anyone to buy or sell; describe evidence and risk. If the signal "
            "label is 'NO TRADE / WAIT FOR CONFIRMATION', say that clearly. Plain text, no markdown.\n\nFacts:\n"
            + dumps(facts)
        )
        try:
            reply = self.models.chat([{"role": "user", "content": prompt}], max_tokens=1500, temperature=0.2, purpose="commentary")
        except AIUnavailable as exc:
            self._update(entry, entry["text"], f"engine (AI unavailable: {str(exc)[:80]})")
            return
        unknown = unverified_numbers(reply.text, facts)
        if unknown:
            self._update(entry, entry["text"], f"engine (AI text rejected: unverified numbers {unknown[:3]})")
            return
        self._update(entry, reply.text.strip(), f"ai:{reply.model}")

    def _update(self, entry: dict, text: str, source: str) -> None:
        self.db.execute("UPDATE commentary SET text = ?, text_source = ? WHERE id = ?", (text, source, entry["id"]))
        self.bus.publish("commentary_update", {"id": entry["id"], "text": text, "text_source": source, "speak": entry["speak"],
                                               "priority": entry["priority"], "symbol": entry["symbol"]})

    def recent(self, limit: int = 100, symbol: str | None = None, mode: str | None = None) -> list[dict]:
        clauses, params = [], []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if mode:
            clauses.append("mode = ?")
            params.append(mode)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.query(f"SELECT * FROM commentary {where} ORDER BY id DESC LIMIT ?", (*params, limit))
        for row in rows:
            row["facts"] = loads(row.pop("payload"))
            row["speak"] = bool(row["speak"])
        return rows

    def reset(self, mode: str | None = None) -> None:
        with self._lock:
            for key in [k for k in self._states if mode is None or k[0] == mode]:
                del self._states[key]
