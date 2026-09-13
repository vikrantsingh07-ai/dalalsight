"""Multi-agent orchestration: runs the technical engine and TradingAgents analysts, normalises results,
computes a confidence-weighted consensus and records every step on the activity timeline."""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from typing import Protocol

from ..agents.llm import AIUnavailable
from ..agents.schema import AGENTS, DIRECTION, AgentResult, AgentSignal, KeyLevel
from ..analysis.signal_engine import LABEL_BEAR, LABEL_BULL, LABEL_HIGH_RISK, LABEL_NO_TRADE
from ..config import RuntimeSettings
from ..data.models import DataUnavailable, now_ist
from ..services.bus import EventBus
from ..services.timeline import Timeline
from ..storage.db import Database, dumps, loads
from .analysis import AnalysisService

NO_TRADE = "NO TRADE / WAIT FOR CONFIRMATION"


class AnalystAdapter(Protocol):
    def run_analyst(self, agent: str, symbol: str, timeframe: str, dashboard_context: str) -> AgentResult: ...

    def run_full_pipeline(self, symbol: str, analysts: list[str]) -> dict: ...


def technical_result(snap: dict) -> AgentResult:
    signal = snap["signal"]
    label = signal["label"]
    view: AgentSignal
    if label in (LABEL_BULL, LABEL_HIGH_RISK) and signal["direction"] > 0:
        view = "BULLISH"
    elif label in (LABEL_BEAR, LABEL_HIGH_RISK) and signal["direction"] < 0:
        view = "BEARISH"
    elif label == LABEL_NO_TRADE:
        view = "NO_TRADE"
    else:
        view = "NEUTRAL"
    levels = snap["levels"]
    key_levels = []
    if levels.get("nearest_support"):
        key_levels.append(KeyLevel(price=levels["nearest_support"]["price"], type="support", note=levels["nearest_support"]["label"][:200]))
    if levels.get("nearest_resistance"):
        key_levels.append(KeyLevel(price=levels["nearest_resistance"]["price"], type="resistance", note=levels["nearest_resistance"]["label"][:200]))
    return AgentResult(
        agent="technical", name=AGENTS["technical"]["name"], timestamp=now_ist().isoformat(), symbol=snap["symbol"],
        timeframe=snap["timeframe"], signal=view, confidence=signal["model_confidence"], confidence_basis="rule_based",
        reasoning=f"{label}; bullish scenario {signal['bullish_pct']}%, model confidence {signal['model_confidence']}%. "
        + "; ".join(signal["reasons"][:3]),
        key_levels=key_levels, risks=signal["risks"][:5], data_sources=signal["data_sources"], status="ok",
    )


def dashboard_context(snap: dict) -> str:
    signal, regime, levels = snap["signal"], snap["regime"], snap["levels"]
    lines = [
        f"As of {snap['generated_at']} ({snap['market']['label']}), {snap['symbol']} {snap['timeframe']} last price {snap['price']:,.2f}.",
        f"Technical engine: {signal['label']}, bullish scenario {signal['bullish_pct']}%, model confidence {signal['model_confidence']}%, coverage {signal['coverage'] * 100:.0f}%.",
        f"Regime: {regime['label']} ({'; '.join(regime['evidence'][:3])}).",
    ]
    if levels.get("nearest_support"):
        lines.append(f"Nearest support {levels['nearest_support']['price']:,.2f} ({levels['nearest_support']['label']}).")
    if levels.get("nearest_resistance"):
        lines.append(f"Nearest resistance {levels['nearest_resistance']['price']:,.2f} ({levels['nearest_resistance']['label']}).")
    if snap.get("options"):
        o = snap["options"]
        lines.append(f"Options ({o['expiry']}): PCR OI {o['pcr_oi']}, max pain {o['max_pain']}, call wall {o['call_wall']}, put wall {o['put_wall']}, ATM IV {o['atm_iv']}.")
    lines.append(f"Data source: {snap['provenance']['provider']}.")
    return "\n".join(lines)


def compute_consensus(results: list[AgentResult], weights: dict[str, float]) -> dict:
    usable = [r for r in results if r.status == "ok" and r.signal in DIRECTION and r.confidence is not None]
    if not usable:
        return {"signal": NO_TRADE, "score": None, "agreement_pct": None, "votes": [], "conflicts": [],
                "reason": "no agent produced a usable view", "method": "confidence × weight direction vote"}
    votes, num, den = [], 0.0, 0.0
    totals = {1: 0.0, -1: 0.0, 0: 0.0}
    for r in usable:
        w = weights.get(r.agent, 1.0)
        c = (r.confidence or 0) / 100
        d = DIRECTION[r.signal]
        num += w * c * d
        den += w * c
        totals[d] += w * c
        votes.append({"agent": r.agent, "name": r.name, "signal": r.signal, "confidence": r.confidence, "weight": w,
                      "basis": r.confidence_basis})
    score = num / den if den else 0.0
    direction = 1 if score >= 0.25 else -1 if score <= -0.25 else 0
    agreement = (totals[direction] / den * 100) if den else 0.0
    conflicts = [
        {"agent": r.agent, "name": r.name, "signal": r.signal, "confidence": r.confidence, "reasoning": r.reasoning[:400]}
        for r in usable if direction and DIRECTION[r.signal] == -direction
    ]
    technical = next((r for r in usable if r.agent == "technical"), None)
    view = "BULLISH" if direction > 0 else "BEARISH" if direction < 0 else "MIXED / NEUTRAL"
    final = view
    reasons = []
    if direction == 0:
        final, reasons = NO_TRADE, ["agents do not agree on a direction"]
    elif agreement < 60:
        final, reasons = NO_TRADE, [f"only {agreement:.0f}% of confidence-weighted evidence agrees"]
    elif technical and technical.signal == "NO_TRADE":
        final, reasons = NO_TRADE, ["technical engine requires confirmation before a trade"]
    return {
        "signal": final,
        "direction_view": view,
        "score": round(score, 3),
        "agreement_pct": round(agreement, 1),
        "votes": votes,
        "conflicts": conflicts,
        "reason": "; ".join(reasons) if reasons else f"{agreement:.0f}% of confidence-weighted evidence agrees",
        "method": "Σ(weight × confidence × direction) ÷ Σ(weight × confidence); LLM confidences are self-assessed, the technical engine's is rule-based",
    }


class AgentOrchestrator:
    def __init__(self, db: Database, analysis: AnalysisService, adapter_factory: Callable[[], AnalystAdapter], timeline: Timeline,
                 bus: EventBus, settings: Callable[[], RuntimeSettings]):
        self.db = db
        self.analysis = analysis
        self._adapter_factory = adapter_factory
        self.timeline = timeline
        self.bus = bus
        self.settings = settings
        self._lock = threading.Lock()
        self.active_run: int | None = None

    def start(self, symbol: str, timeframe: str, agents: list[str], kind: str = "analysts") -> int:
        unknown = [a for a in agents if a not in AGENTS or a == "technical"]
        if unknown:
            raise ValueError(f"unknown agents: {unknown}")
        if not self._lock.acquire(blocking=False):
            raise RuntimeError(f"agent run {self.active_run} is still in progress")
        try:
            run_id = self.db.execute(
                "INSERT INTO agent_runs(started_at, kind, symbol, timeframe, status, results) VALUES (?, ?, ?, ?, 'running', ?)",
                (now_ist().isoformat(), kind, symbol, timeframe, dumps([])),
            )
        except Exception:
            self._lock.release()
            raise
        self.active_run = run_id
        threading.Thread(target=self._run, args=(run_id, symbol, timeframe, agents, kind), daemon=True).start()
        return run_id

    def _save(self, run_id: int, results: list[AgentResult], **fields) -> None:
        sets = ["results = ?"]
        params: list = [dumps([r.model_dump() for r in results])]
        for key, value in fields.items():
            sets.append(f"{key} = ?")
            params.append(dumps(value) if key == "consensus" else value)
        self.db.execute(f"UPDATE agent_runs SET {', '.join(sets)} WHERE id = ?", (*params, run_id))

    def _run(self, run_id: int, symbol: str, timeframe: str, agents: list[str], kind: str) -> None:
        results: list[AgentResult] = []
        model_used = None
        try:
            self.timeline.add("agents", f"Agent run #{run_id} started for {symbol} {timeframe}: {', '.join(['technical', *agents])}", symbol)
            snap = self.analysis.snapshot(symbol, timeframe)
            results.append(technical_result(snap))
            self._progress(run_id, results)
            context = dashboard_context(snap)
            adapter = self._adapter_factory()
            if kind == "full_pipeline":
                self.timeline.add("agents", f"Full TradingAgents pipeline started for {symbol}", symbol)
                full = adapter.run_full_pipeline(symbol, agents)
                model_used = full["model"]
                for agent in agents:
                    results.append(AgentResult(agent=agent, name=AGENTS[agent]["name"], timestamp=now_ist().isoformat(), symbol=symbol,
                                               timeframe=timeframe, signal="UNPARSED", report=full["reports"].get(agent, ""),
                                               model=full["model"], status="ok", reasoning="Report from the full pipeline run."))
                results.append(AgentResult(agent="portfolio_manager", name="Portfolio Manager (TradingAgents)", timestamp=now_ist().isoformat(),
                                           symbol=symbol, timeframe=timeframe, signal=full["signal"], confidence=None,
                                           reasoning=f"Final rating: {full['rating']}", report=full["final_trade_decision"],
                                           model=full["model"], status="ok", warnings=[f"{full['model_calls']} model calls"]))
            else:
                for agent in agents:
                    self.timeline.add("agents", f"{AGENTS[agent]['name']} started ({symbol})", symbol)
                    self.bus.publish("agent_progress", {"run_id": run_id, "agent": agent, "status": "running"})
                    try:
                        result = adapter.run_analyst(agent, symbol, timeframe, context)
                        model_used = result.model or model_used
                    except AIUnavailable as exc:
                        result = self._failed(agent, symbol, timeframe, f"AI unavailable: {exc}")
                    except DataUnavailable as exc:
                        result = self._failed(agent, symbol, timeframe, str(exc))
                    except Exception as exc:  # noqa: BLE001 — one failing agent must not stop the others
                        result = self._failed(agent, symbol, timeframe, f"{type(exc).__name__}: {str(exc)[:300]}")
                        self.timeline.error("agents", f"{agent} failed", traceback.format_exc())
                    results.append(result)
                    self.timeline.add("agents", f"{result.name}: {result.signal}" + (f" ({result.confidence:.0f}%)" if result.confidence is not None else "")
                                      + (f" — {result.error}" if result.error else ""), symbol)
                    self._progress(run_id, results)
            consensus = compute_consensus(results, self.settings().agents.agent_weights | {"technical": 1.0})
            self._save(run_id, results, status="completed", finished_at=now_ist().isoformat(), consensus=consensus, model=model_used)
            self.timeline.add("agents", f"Agent run #{run_id} consensus: {consensus['signal']} ({consensus['reason']})", symbol, {"run_id": run_id})
            self.bus.publish("agent_run", self.get(run_id))
        except Exception as exc:  # noqa: BLE001
            self._save(run_id, results, status="failed", finished_at=now_ist().isoformat(), error=f"{type(exc).__name__}: {str(exc)[:400]}")
            self.timeline.error("agents", f"Agent run #{run_id} failed: {exc}", traceback.format_exc())
            self.bus.publish("agent_run", self.get(run_id))
        finally:
            self.active_run = None
            self._lock.release()

    def _failed(self, agent: str, symbol: str, timeframe: str, error: str) -> AgentResult:
        return AgentResult(agent=agent, name=AGENTS[agent]["name"], timestamp=now_ist().isoformat(), symbol=symbol, timeframe=timeframe,
                           signal="ERROR", status="error", error=error[:500])

    def _progress(self, run_id: int, results: list[AgentResult]) -> None:
        self._save(run_id, results)
        self.bus.publish("agent_progress", {"run_id": run_id, "results": [r.model_dump(exclude={"report"}) for r in results]})

    def get(self, run_id: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM agent_runs WHERE id = ?", (run_id,))
        if row:
            row["results"], row["consensus"] = loads(row["results"]) or [], loads(row["consensus"])
        return row

    def list(self, limit: int = 50, symbol: str | None = None) -> list[dict]:
        if symbol:
            rows = self.db.query("SELECT id, started_at, finished_at, kind, symbol, timeframe, status, model, consensus, error FROM agent_runs WHERE symbol = ? ORDER BY id DESC LIMIT ?", (symbol, limit))
        else:
            rows = self.db.query("SELECT id, started_at, finished_at, kind, symbol, timeframe, status, model, consensus, error FROM agent_runs ORDER BY id DESC LIMIT ?", (limit,))
        for row in rows:
            row["consensus"] = loads(row["consensus"])
        return rows

    def latest_consensus(self, symbol: str) -> dict | None:
        row = self.db.query_one("SELECT id, finished_at, consensus FROM agent_runs WHERE symbol = ? AND status = 'completed' ORDER BY id DESC LIMIT 1", (symbol,))
        return None if not row else {"run_id": row["id"], "finished_at": row["finished_at"], **(loads(row["consensus"]) or {})}
