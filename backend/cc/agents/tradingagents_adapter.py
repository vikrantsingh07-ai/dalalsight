"""Adapter that runs the existing TradingAgents analysts unchanged.

Each analyst runs in a small LangGraph (analyst ⇄ its tool node) built from the same factories,
tool nodes and routing that ``TradingAgentsGraph`` uses, with the live dashboard snapshot appended
to the instrument context. One extra LLM call converts the report into the shared schema.
The full TradingAgents pipeline (debate → trader → risk → portfolio manager) is also available.
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
from datetime import date

import openai
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError
from tradingagents.agents import (
    create_derivatives_analyst,
    create_fundamentals_analyst,
    create_market_analyst,
    create_msg_delete,
    create_news_analyst,
    create_sentiment_analyst,
)
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.dataflows.india.instruments import asset_type_for, parse_indian_symbol
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.analyst_execution import build_analyst_execution_plan
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.llm_clients import create_llm_client

from ..config import EnvConfig
from ..data.models import now_ist
from .llm import AIUnavailable, ModelManager, numbers_in, unverified_numbers
from .schema import AGENTS, AgentResult, ExtractedView

FACTORIES = {
    "market": create_market_analyst,
    "social": create_sentiment_analyst,
    "news": create_news_analyst,
    "fundamentals": create_fundamentals_analyst,
    "derivatives": create_derivatives_analyst,
}
REPORT_KEYS = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
    "derivatives": "derivatives_report",
}
RATING_SIGNAL = {"BUY": "BULLISH", "OVERWEIGHT": "BULLISH", "HOLD": "NEUTRAL", "UNDERWEIGHT": "BEARISH", "SELL": "BEARISH"}


class AnalystBudgetExceeded(RuntimeError):
    """An analyst hit its model-call cap or wall-clock budget."""


_TRANSIENT_TEXT = re.compile(r"overloaded|temporarily unavailable|rate.?limit|timed out|\b(429|50[0-9])\b", re.IGNORECASE)


def _parse_json_object(text: str) -> dict:
    """First JSON object in a model reply, tolerating code fences, surrounding prose and trailing commas."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in the reply")
    raw = match.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", raw))


def _is_transient(exc: BaseException) -> bool:
    """Provider-side failures worth one retry on another model (not budget stops or code errors)."""
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError, openai.RateLimitError)):
        return True
    return isinstance(exc, ValueError) and bool(_TRANSIENT_TEXT.search(str(exc)))


class UsageCallback(BaseCallbackHandler):
    """Counts every LangChain model attempt against the daily AI budget, enforces the analyst's call cap and
    time budget, and cools down failing models.

    LangGraph checks its recursion limit only between nodes, and upstream retries happen inside one node, so
    the cap is enforced here, before each request is sent.
    """

    raise_error = True  # budget violations must stop the graph, not just be logged

    def __init__(self, models: ModelManager, model: str, max_calls: int | None = None, deadline: float | None = None):
        self.models = models
        self.model = model
        self.max_calls = max_calls
        self.deadline = deadline
        self.calls = 0

    def _admit(self) -> None:
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise AnalystBudgetExceeded(f"stopped after {self.calls} model calls (cap {self.max_calls})")
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise AnalystBudgetExceeded(f"stopped after {self.calls} model calls: analyst time budget exhausted")
        self.calls += 1
        self.models.record_call(True)

    def on_chat_model_start(self, serialized, messages, **kwargs):  # noqa: ANN001
        self._admit()

    def on_llm_start(self, serialized, prompts, **kwargs):  # noqa: ANN001
        self._admit()

    def on_llm_error(self, error, **kwargs):  # noqa: ANN001
        # the next run (or assistant/commentary call) then prefers the fallback model
        self.models.cooldown(self.model, f"{type(error).__name__}: {str(error)[:120]}")


def ta_symbol_info(symbol: str) -> tuple[str, bool]:
    inst = parse_indian_symbol(symbol, india_mode=True)
    if inst is None:
        return "stock", False
    return asset_type_for(inst), bool(getattr(inst, "has_derivatives", False) or asset_type_for(inst) in ("index",))


class TradingAgentsAdapter:
    def __init__(self, env: EnvConfig, models: ModelManager, max_tool_rounds: int = 8, max_minutes: int = 15):
        self.env = env
        self.models = models
        self.max_tool_rounds = max_tool_rounds
        self.max_minutes = max_minutes
        # TradingAgents retries "overloaded" responses up to 3 times inside one call; the Command Center has its
        # own fallback model and budgets, so one retry is enough (an explicit env value still wins).
        os.environ.setdefault("TRADINGAGENTS_UPSTREAM_RETRIES", "1")

    def _config(self, model: str) -> dict:
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg.update({
            "market": "india",
            "llm_provider": self.env.ai_provider,
            "quick_think_llm": model,
            "deep_think_llm": model,
            "backend_url": self.env.ai_base_url,
            "checkpoint_enabled": False,
            "max_debate_rounds": 1,
            "max_risk_discuss_rounds": 1,
            "llm_max_retries": 1,
        })
        return cfg

    def _model(self, calls_needed: int) -> str:
        self.models.ensure_ready(calls_needed)
        model = self.models.active_model()
        if model is None:
            raise AIUnavailable("no configured AI model is currently available (see System Health)")
        return model

    def run_analyst(self, agent: str, symbol: str, timeframe: str, dashboard_context: str) -> AgentResult:
        """Run one analyst. A transient provider failure (timeout, overload, 5xx, rate limit) cools that model down
        and retries once on the next available model, within the same time budget."""
        started = time.perf_counter()
        deadline = time.monotonic() + self.max_minutes * 60
        failed: list[str] = []
        while True:
            model = self._model(AGENTS[agent]["est_calls"] + 1)
            try:
                result = self._run_once(agent, symbol, timeframe, dashboard_context, model, deadline, started)
            except Exception as exc:  # noqa: BLE001 — only transient provider errors are retried
                if not _is_transient(exc) or failed or time.monotonic() > deadline:
                    raise
                self.models.cooldown(model, f"{type(exc).__name__}: {str(exc)[:120]}")
                failed.append(f"{model} ({type(exc).__name__})")
                if self.models.active_model() in (None, model):
                    raise
                continue
            if failed:
                result.warnings.insert(0, f"retried on {model} after {failed[0]}")
            return result

    def _run_once(self, agent: str, symbol: str, timeframe: str, dashboard_context: str, model: str, deadline: float,
                  started: float) -> AgentResult:
        meta = AGENTS[agent]
        base = {"agent": agent, "name": meta["name"], "timestamp": now_ist().isoformat(), "symbol": symbol, "timeframe": timeframe}
        asset_type, _ = ta_symbol_info(symbol)
        usage = UsageCallback(self.models, model, max_calls=2 * self.max_tool_rounds + 4, deadline=deadline)
        trade_date = now_ist().date().isoformat()
        graph = TradingAgentsGraph(selected_analysts=[agent], config=self._config(model), callbacks=[usage])
        context = graph.resolve_instrument_context(symbol, asset_type, trade_date)
        context += (
            "\n\nLive Command Center snapshot (computed from the dashboard's market-data provider; "
            "use it as current context and prefer your tools for detail):\n" + dashboard_context
        )
        state = graph.propagator.create_initial_state(symbol, trade_date, asset_type, "", context)
        spec = build_analyst_execution_plan([agent]).specs[0]
        workflow = StateGraph(AgentState)
        # Same analyst factory and tools as TradingAgentsGraph, with a bounded request timeout so a hung
        # free-tier request cannot stall the run for the client's default of several minutes.
        llm = create_llm_client(self.env.ai_provider, model, base_url=self.env.ai_base_url, timeout=self.env.ai_timeout_seconds,
                                max_retries=1, callbacks=[usage]).get_llm()
        workflow.add_node(spec.agent_node, FACTORIES[agent](llm))
        workflow.add_node(spec.tool_node, graph.tool_nodes[agent])
        workflow.add_node(spec.clear_node, create_msg_delete())
        workflow.add_edge(START, spec.agent_node)
        workflow.add_conditional_edges(spec.agent_node, getattr(graph.conditional_logic, f"should_continue_{agent}"),
                                       [spec.tool_node, spec.clear_node])
        workflow.add_edge(spec.tool_node, spec.agent_node)
        workflow.add_edge(spec.clear_node, END)
        # Stream so the gathered tool outputs survive if the analyst hits its round cap or time budget.
        final: dict | None = None
        stop_reason: str | None = None
        try:
            for value in workflow.compile().stream(state, config={"recursion_limit": 2 * self.max_tool_rounds + 4, "callbacks": [usage]},
                                                   stream_mode="values"):
                final = value
        except (GraphRecursionError, AnalystBudgetExceeded) as exc:
            stop_reason = str(exc).split(". ")[0]
        report = ((final or {}).get(REPORT_KEYS[agent]) or "").strip()
        notes: list[str] = []
        if not report and stop_reason and final:
            report, unknown = self._finalise_report(meta["name"], symbol, final.get("messages", []))
            if report:
                notes.append(f"report finalised from the analyst's tool outputs after: {stop_reason}")
            if unknown:
                notes.append(f"{len(unknown)} figure(s) in the finalised report not found in tool outputs: {unknown[:5]}")
        if not report:
            return AgentResult(**base, signal="ERROR", status="error", error=stop_reason or "analyst returned an empty report", model=model,
                               duration_s=round(time.perf_counter() - started, 1))
        view, warnings = self.extract(meta["name"], report)
        warnings = notes + warnings
        result = AgentResult(
            **base,
            signal=view.signal if view else "UNPARSED",
            confidence=view.confidence if view else None,
            confidence_basis="llm_assessed" if view else "none",
            reasoning=view.reasoning if view else "Structured extraction failed; read the full report.",
            key_levels=view.key_levels if view else [],
            risks=view.risks if view else [],
            data_sources=view.data_sources if view else [],
            report=report,
            model=model,
            duration_s=round(time.perf_counter() - started, 1),
            warnings=warnings + [f"{usage.calls} model calls"],
        )
        return result

    def _finalise_report(self, name: str, symbol: str, messages: list) -> tuple[str, list[float]]:
        """Write the analyst's report from the tool outputs it already gathered (one model call)."""
        outputs = [str(m.content) for m in messages if isinstance(m, ToolMessage) and m.content]
        if not outputs:
            return "", []
        parts: list[str] = []
        remaining = 14000
        for text in outputs:
            if remaining <= 0:
                break
            parts.append(text[:remaining])
            remaining -= len(parts[-1])
        prompt = (
            f"You are the {name} for {symbol}. You gathered the tool outputs below but ran out of tool rounds before "
            "writing your report. Write the report now using ONLY these outputs: state the data dates, the key readings, "
            "the directional bias (bullish, bearish, range-bound or unclear), key levels and what would invalidate the "
            "view, and end with a Markdown summary table. Do not introduce any number that is not in the outputs.\n\n"
            "TOOL OUTPUTS:\n" + "\n\n---\n\n".join(parts)
        )
        try:
            reply = self.models.chat([{"role": "user", "content": prompt}], max_tokens=3000, temperature=0.2, purpose="report finalisation")
        except AIUnavailable:
            return "", []
        return reply.text, unverified_numbers(reply.text, parts)

    def extract(self, name: str, report: str) -> tuple[ExtractedView | None, list[str]]:
        prompt = (
            f"Read the {name} report below and return ONLY a JSON object (no prose, no code fences) with keys:\n"
            '"signal": "BULLISH" | "BEARISH" | "NEUTRAL" | "NO_TRADE" (NO_TRADE when the report says evidence is insufficient or data is unavailable),\n'
            '"confidence": number 0-100 for how strongly the report\'s own evidence supports that signal,\n'
            '"reasoning": 2-4 sentences summarising the evidence in the report,\n'
            '"key_levels": [{"price": number, "type": "support"|"resistance"|"target"|"stop"|"other", "note": short text}] using only prices written in the report,\n'
            '"risks": [short strings], "data_sources": [data sources or tools named in the report].\n\nREPORT:\n'
            + report[:14000]
        )
        warnings: list[str] = []
        messages = [{"role": "user", "content": prompt}]
        view: ExtractedView | None = None
        for attempt in (1, 2):  # free models sometimes emit malformed JSON: one corrective retry
            try:
                reply = self.models.chat(messages, max_tokens=2000, temperature=0.0, purpose="extraction")
            except AIUnavailable as exc:
                return None, warnings + [f"extraction skipped: {exc}"]
            try:
                view = ExtractedView.model_validate(_parse_json_object(reply.text))
                break
            except (ValueError, ValidationError) as exc:
                problem = str(exc)[:200]
                warnings.append(f"extraction attempt {attempt} invalid: {problem[:120]}")
                messages = messages + [
                    {"role": "assistant", "content": reply.text},
                    {"role": "user", "content": f"That was not valid JSON for the required keys ({problem}). Return ONLY the corrected JSON object."},
                ]
        if view is None:
            return None, warnings
        report_numbers = numbers_in(report)
        kept = []
        for level in view.key_levels:
            if any(abs(level.price - n) <= max(0.051, n * 0.0006) for n in report_numbers):
                kept.append(level)
            else:
                warnings.append(f"dropped level {level.price} not found in report")
        view.key_levels = kept
        return view, warnings

    def run_full_pipeline(self, symbol: str, analysts: list[str]) -> dict:
        model = self._model(30)
        usage = UsageCallback(self.models, model, deadline=time.monotonic() + 4 * self.max_minutes * 60)
        asset_type, _ = ta_symbol_info(symbol)
        trade_date = date.today().isoformat()
        graph = TradingAgentsGraph(selected_analysts=analysts, config=self._config(model), callbacks=[usage])
        final_state, rating = graph.propagate(symbol, trade_date, asset_type=asset_type)
        reports = {agent: final_state.get(REPORT_KEYS[agent], "") for agent in analysts}
        return {
            "model": model,
            "rating": rating,
            "signal": RATING_SIGNAL.get(str(rating).upper(), "UNPARSED"),
            "final_trade_decision": final_state.get("final_trade_decision", ""),
            "investment_plan": final_state.get("investment_plan", ""),
            "trader_plan": final_state.get("trader_investment_plan", ""),
            "reports": reports,
            "model_calls": usage.calls,
        }
