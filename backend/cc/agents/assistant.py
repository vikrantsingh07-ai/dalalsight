"""Conversational trading assistant grounded in the dashboard's live analysis.

The assistant gathers facts from the engines (signal, regime, levels, events, option chain,
agent consensus) for the symbol/timeframe/expiry/strike in context, asks the model to answer in a
fixed nine-part structure using only those facts, and rejects answers containing numbers that are
not in the facts. Without a usable model it answers from the engines directly.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..analysis.signal_engine import DISCLAIMER, LABEL_NO_TRADE
from ..config import TIMEFRAMES
from ..data.models import DataUnavailable, now_ist
from ..data.symbols import INDEX_TABLE, SymbolRegistry
from ..storage.db import Database, dumps, loads
from .llm import AIUnavailable, ModelManager, unverified_numbers

SYMBOL_PHRASES = [
    ("BANK NIFTY", "BANKNIFTY"), ("BANKNIFTY", "BANKNIFTY"), ("FIN NIFTY", "FINNIFTY"), ("FINNIFTY", "FINNIFTY"),
    ("MIDCAP NIFTY", "MIDCPNIFTY"), ("MIDCPNIFTY", "MIDCPNIFTY"), ("SENSEX", "SENSEX"), ("INDIA VIX", "INDIAVIX"),
    ("NIFTY", "NIFTY"),
]
STRIKE_RE = re.compile(r"\b(\d{3,6}(?:\.\d+)?)\s*(CE|PE|CALLS?|PUTS?)\b", re.IGNORECASE)
TF_RE = re.compile(r"\b(1|3|5|15|30)\s*(?:m|min|mins|minute|minutes)\b|\b(1h|hourly|4h|daily|weekly)\b", re.IGNORECASE)
TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9&]{2,19}\b")
STOPWORDS = {"CE", "PE", "ATM", "OTM", "ITM", "PCR", "OI", "IV", "VWAP", "EMA", "RSI", "MACD", "ATR", "ADX", "NSE", "BSE", "FII", "DII",
             "THE", "AND", "FOR", "BUY", "SELL", "WHAT", "WHY", "HOW", "NOW", "TODAY", "LONG", "SHORT", "CALL", "PUT", "NO", "YES"}

SECTIONS = ["Direct answer", "Market context", "Technical evidence", "Options evidence", "Key levels", "Scenarios",
            "Trade plan", "Risks and invalidation", "Confidence and data limitations"]

SYSTEM_PROMPT = (
    "You are the AI assistant inside an Indian-markets trading command center. Answer using ONLY the JSON facts "
    "provided; they were computed from live market data by the platform's engines.\n"
    "Rules:\n- Never invent prices, levels, probabilities, statistics or dates; every number you write must appear in the facts.\n"
    f"- If the technical signal label is '{LABEL_NO_TRADE}' or the evidence is insufficient or contradictory, the direct answer must be '{LABEL_NO_TRADE}'.\n"
    "- Scenario percentages are model estimates from current signals, not guarantees.\n"
    "- Provide research support, not personalised investment advice; do not tell the user what to do with their own money.\n"
    "- If data is unavailable, say so plainly.\n"
    "Structure the answer with exactly these numbered headings: " + "; ".join(f"{i + 1}. {s}" for i, s in enumerate(SECTIONS))
    + ". Keep it under 350 words, plain text with short bullet points."
)


class ChatContext(BaseModel):
    symbol: str = Field("NIFTY", max_length=32)
    timeframe: str = "5m"
    expiry: str | None = Field(None, max_length=10)
    strike: float | None = Field(None, gt=0)
    option_type: Literal["CE", "PE"] | None = None

    @field_validator("timeframe")
    @classmethod
    def _tf(cls, value: str) -> str:
        if value not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {TIMEFRAMES}")
        return value


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    context: ChatContext = Field(default_factory=ChatContext)
    session: str = Field("default", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    use_ai: bool = True


class Assistant:
    def __init__(self, analysis, options, orchestrator, commentary, models: ModelManager, db: Database, registry: SymbolRegistry):
        self.analysis = analysis
        self.options = options
        self.orchestrator = orchestrator
        self.commentary = commentary
        self.models = models
        self.db = db
        self.registry = registry

    def resolve_context(self, req: ChatIn) -> dict:
        ctx = req.context.model_dump()
        ctx["symbol"] = self.registry.normalize(ctx["symbol"])
        question = req.question
        upper = question.upper()
        for phrase, symbol in SYMBOL_PHRASES:
            if phrase in upper:
                ctx["symbol"] = symbol
                break
        else:
            try:
                equities = self.registry.equities()
            except DataUnavailable:
                equities = {}
            for token in TOKEN_RE.findall(question):
                if token not in STOPWORDS and (token in equities or token in INDEX_TABLE):
                    ctx["symbol"] = token
                    break
        strike = STRIKE_RE.search(question)
        if strike:
            ctx["strike"] = float(strike.group(1))
            ctx["option_type"] = "CE" if strike.group(2).upper().startswith(("CE", "CALL")) else "PE"
        tf = TF_RE.search(question)
        if tf:
            if tf.group(1):
                ctx["timeframe"] = f"{tf.group(1)}m"
            else:
                ctx["timeframe"] = {"1h": "1h", "hourly": "1h", "4h": "4h", "daily": "1D", "weekly": "1W"}[tf.group(2).lower()]
        return ctx

    def gather(self, ctx: dict) -> dict:
        symbol, timeframe = ctx["symbol"], ctx["timeframe"]
        facts: dict = {"context": ctx, "generated_at": now_ist().isoformat()}
        facts["market_status"] = self.analysis.market_status().to_dict()
        try:
            snap = self.analysis.snapshot(symbol, timeframe)
            signal = snap["signal"]
            facts["technical"] = {
                "price": snap["price"], "bar_time": snap["bar_time"], "data_source": snap["provenance"]["provider"],
                "signal_label": signal["label"], "bullish_scenario_pct": signal["bullish_pct"],
                "bearish_scenario_pct": signal["bearish_pct"], "model_confidence_pct": signal["model_confidence"],
                "data_coverage_pct": round(signal["coverage"] * 100, 1), "reasons": signal["reasons"], "risks": signal["risks"],
                "plan": signal["plan"],
                "components": [{"name": c["name"], "available": c["available"], "score": c["score"], "evidence": c["evidence"][:3],
                                "unavailable_reason": c["unavailable_reason"]} for c in signal["components"]],
                "regime": {"label": snap["regime"]["label"], "evidence": snap["regime"]["evidence"]},
                "nearest_support": snap["levels"]["nearest_support"], "nearest_resistance": snap["levels"]["nearest_resistance"],
                "breakout_level": snap["levels"]["breakout_level"], "breakdown_level": snap["levels"]["breakdown_level"],
                "recent_events": [e["message"] for e in snap["events"]],
                "indicators": snap["technical"],
            }
            if snap.get("options_status"):
                facts["options_status"] = snap["options_status"]
        except DataUnavailable as exc:
            facts["technical"] = exc.to_dict()
        meta = self.registry.meta(symbol)
        if meta.option_type:
            try:
                summary = self.options.summary(symbol, ctx.get("expiry"))
                facts["options"] = {k: summary[k] for k in ("expiry", "days_to_expiry", "spot", "atm_strike", "atm_iv", "atm_straddle",
                                                             "expected_range", "pcr_oi", "pcr_volume", "max_pain", "call_wall", "put_wall",
                                                             "iv_skew", "interpretation", "timestamp", "lot_size")}
                if ctx.get("strike") and ctx.get("option_type"):
                    row = next((r for r in summary["table"] if abs(r["strike"] - ctx["strike"]) < 1e-6), None)
                    leg = row[ctx["option_type"].lower()] if row else None
                    facts["contract"] = {"strike": ctx["strike"], "option_type": ctx["option_type"], "expiry": summary["expiry"], **(leg or {})} \
                        if leg else {"status": "unavailable", "reason": f"strike {ctx['strike']:g} {ctx['option_type']} not in the chain window around ATM"}
            except DataUnavailable as exc:
                facts["options"] = exc.to_dict()
        else:
            facts["options"] = {"status": "unavailable", "reason": "no NSE-listed options for this instrument"}
        facts["agent_consensus"] = self.orchestrator.latest_consensus(symbol)
        facts["recent_commentary"] = [c["text"] for c in self.commentary.recent(3, symbol=symbol)]
        return facts

    @staticmethod
    def engine_answer(facts: dict) -> str:
        t = facts.get("technical") or {}
        o = facts.get("options") or {}
        lines = []
        if t.get("status") == "unavailable":
            lines.append(f"1. Direct answer\n{LABEL_NO_TRADE} — technical data unavailable ({t.get('reason')}).")
        else:
            lines.append(f"1. Direct answer\n{t['signal_label']} on {facts['context']['symbol']} {facts['context']['timeframe']}.")
        m = facts["market_status"]
        lines.append(f"2. Market context\n{m['label']} ({m['reason']}). " + (f"Regime: {t['regime']['label']}." if t.get("regime") else ""))
        if t.get("reasons") is not None:
            lines.append("3. Technical evidence\n" + ("\n".join(f"- {r}" for r in t["reasons"][:5]) or "- no components agree strongly"))
        if o.get("status") == "unavailable":
            lines.append(f"4. Options evidence\nData unavailable: {o.get('reason')}.")
        elif o:
            lines.append("4. Options evidence\n" + "\n".join(f"- {n}" for n in o.get("interpretation", [])))
        levels = []
        if t.get("nearest_support"):
            levels.append(f"- Support {t['nearest_support']['price']:,.2f} ({t['nearest_support']['label']})")
        if t.get("nearest_resistance"):
            levels.append(f"- Resistance {t['nearest_resistance']['price']:,.2f} ({t['nearest_resistance']['label']})")
        lines.append("5. Key levels\n" + ("\n".join(levels) or "- none detected"))
        if t.get("bullish_scenario_pct") is not None:
            lines.append(f"6. Scenarios\n- Bullish {t['bullish_scenario_pct']}% / bearish {t['bearish_scenario_pct']}% (model-estimated from current signals)")
        plan = t.get("plan")
        if plan and t.get("signal_label") != LABEL_NO_TRADE:
            lines.append(f"7. Trade plan\n- Entry {plan['entry_low']:,.2f}–{plan['entry_high']:,.2f}; stop {plan['stop']:,.2f} ({plan['stop_basis']}); "
                         f"T1 {plan['target1']:,.2f}; T2 {plan['target2']:,.2f}; R:R 1:{plan['risk_reward']}")
        else:
            lines.append("7. Trade plan\n- None: wait for confirmation.")
        lines.append("8. Risks and invalidation\n" + ("\n".join(f"- {r}" for r in (t.get("risks") or [])[:5]) or "- see levels")
                     + (f"\n- Invalidation: {plan['invalidation']}" if plan else ""))
        missing = [c["name"] for c in t.get("components", []) if not c["available"]]
        lines.append(f"9. Confidence and data limitations\n- Model confidence {t.get('model_confidence_pct', 'n/a')}%, data coverage {t.get('data_coverage_pct', 'n/a')}%"
                     + (f"\n- Unavailable: {', '.join(missing)}" if missing else "") + f"\n- {DISCLAIMER}")
        return "\n\n".join(lines)

    def answer(self, req: ChatIn) -> dict:
        ctx = self.resolve_context(req)
        facts = self.gather(ctx)
        text, source = self.engine_answer(facts), "engine"
        if req.use_ai:
            try:
                reply = self.models.chat(
                    [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": f"Question: {req.question}\n\nFacts (JSON):\n{dumps(facts)}"}],
                    max_tokens=3000, temperature=0.2, purpose="assistant",
                )
                unknown = unverified_numbers(reply.text, facts)
                if unknown:
                    source = f"engine (AI answer rejected: unverified numbers {unknown[:3]})"
                else:
                    text, source = reply.text, f"ai:{reply.model}"
            except AIUnavailable as exc:
                source = f"engine (AI unavailable: {str(exc)[:120]})"
        ts = now_ist().isoformat()
        self.db.execute("INSERT INTO chat_messages(ts, session, role, content, payload) VALUES (?, ?, 'user', ?, ?)",
                        (ts, req.session, req.question, dumps({"context": ctx})))
        self.db.execute("INSERT INTO chat_messages(ts, session, role, content, payload) VALUES (?, ?, 'assistant', ?, ?)",
                        (now_ist().isoformat(), req.session, text, dumps({"source": source, "context": ctx})))
        return {"answer": text, "source": source, "context": ctx, "facts": facts, "ts": ts}

    def history(self, session: str, limit: int = 50) -> list[dict]:
        rows = self.db.query("SELECT * FROM chat_messages WHERE session = ? ORDER BY id DESC LIMIT ?", (session, limit))
        for row in rows:
            row["payload"] = loads(row["payload"])
        return list(reversed(rows))
