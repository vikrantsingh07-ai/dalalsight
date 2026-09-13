"""Shared output schema for every agent (LLM analysts and the rule-based technical engine)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AgentSignal = Literal["BULLISH", "BEARISH", "NEUTRAL", "NO_TRADE", "UNPARSED", "ERROR", "SKIPPED"]

AGENTS: dict[str, dict] = {
    "technical": {"name": "Technical Engine", "kind": "rule_based", "est_calls": 0,
                  "description": "Deterministic indicators, levels, regime and signal confidence engine"},
    "market": {"name": "Market Analyst", "kind": "llm", "est_calls": 6,
               "description": "TradingAgents market analyst: price action and technical indicators"},
    "social": {"name": "Sentiment Analyst", "kind": "llm", "est_calls": 3,
               "description": "TradingAgents social/sentiment analyst from news flow"},
    "news": {"name": "News Analyst", "kind": "llm", "est_calls": 4,
             "description": "TradingAgents news analyst: company, India and global macro news"},
    "fundamentals": {"name": "Fundamentals Analyst", "kind": "llm", "est_calls": 5,
                     "description": "TradingAgents fundamentals analyst: statements, valuation, index fundamentals"},
    "derivatives": {"name": "Derivatives (F&O) Analyst", "kind": "llm", "est_calls": 6,
                    "description": "TradingAgents F&O analyst: futures basis, OI build-up, option chain, FII positioning, VIX"},
}
DIRECTION = {"BULLISH": 1, "BEARISH": -1, "NEUTRAL": 0, "NO_TRADE": 0}


class KeyLevel(BaseModel):
    price: float
    type: Literal["support", "resistance", "target", "stop", "other"] = "other"
    note: str = Field("", max_length=200)


class AgentResult(BaseModel):
    agent: str
    name: str
    timestamp: str
    symbol: str
    timeframe: str
    signal: AgentSignal
    confidence: float | None = Field(None, ge=0, le=100)
    confidence_basis: Literal["rule_based", "llm_assessed", "none"] = "none"
    reasoning: str = ""
    key_levels: list[KeyLevel] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    report: str = ""
    model: str | None = None
    status: Literal["ok", "error", "skipped", "running"] = "ok"
    error: str | None = None
    duration_s: float | None = None
    warnings: list[str] = Field(default_factory=list)


class ExtractedView(BaseModel):
    signal: Literal["BULLISH", "BEARISH", "NEUTRAL", "NO_TRADE"]
    confidence: float = Field(ge=0, le=100)
    reasoning: str = Field(max_length=1500)
    key_levels: list[KeyLevel] = Field(default_factory=list, max_length=12)
    risks: list[str] = Field(default_factory=list, max_length=10)
    data_sources: list[str] = Field(default_factory=list, max_length=12)
