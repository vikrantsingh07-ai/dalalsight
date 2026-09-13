import os
import time

import httpx
import openai
import pytest
from helpers import SECRET, make_env
from langchain_core.messages import AIMessage, ToolMessage

from cc.agents.llm import LLMReply, ModelManager
from cc.agents.schema import AgentResult
from cc.agents.tradingagents_adapter import AnalystBudgetExceeded, TradingAgentsAdapter, UsageCallback
from cc.storage.db import Database


def test_usage_callback_enforces_call_cap_and_counts_budget():
    models = ModelManager(make_env(), Database(":memory:"))
    usage = UsageCallback(models, "test/default-550b", max_calls=2)
    assert usage.raise_error is True  # LangChain must propagate the stop instead of logging it
    usage.on_chat_model_start({}, [[]])
    usage.on_chat_model_start({}, [[]])
    with pytest.raises(AnalystBudgetExceeded, match="cap 2"):
        usage.on_chat_model_start({}, [[]])
    assert usage.calls == 2 and models.calls_today() == 2  # the refused request is not counted


def test_usage_callback_enforces_deadline():
    models = ModelManager(make_env(), Database(":memory:"))
    late = UsageCallback(models, "test/default-550b", deadline=time.monotonic() - 1)
    with pytest.raises(AnalystBudgetExceeded, match="time budget"):
        late.on_llm_start({}, ["prompt"])
    assert models.calls_today() == 0


def test_model_errors_cool_the_model_down():
    models = ModelManager(make_env(), Database(":memory:"))
    models._models, models._models_checked = {"test/default-550b", "test/fallback-120b"}, time.time()
    UsageCallback(models, "test/default-550b").on_llm_error(TimeoutError("read timed out"))
    assert models.active_model() == "test/fallback-120b"


def _two_model_manager(monkeypatch) -> ModelManager:
    monkeypatch.setenv("CC_TEST_AI_KEY", SECRET)
    models = ModelManager(make_env(), Database(":memory:"))
    models._models, models._models_checked = {"test/default-550b", "test/fallback-120b"}, time.time()
    return models


def test_transient_failure_retries_analyst_on_fallback_model(monkeypatch):
    models = _two_model_manager(monkeypatch)
    adapter = TradingAgentsAdapter(make_env(), models)
    tried: list[str] = []

    def fake_run_once(agent, symbol, timeframe, context, model, deadline, started):
        tried.append(model)
        if model == "test/default-550b":
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
        return AgentResult(agent=agent, name="Market Analyst", timestamp="t", symbol=symbol, timeframe=timeframe, signal="NEUTRAL", model=model)

    monkeypatch.setattr(adapter, "_run_once", fake_run_once)
    result = adapter.run_analyst("market", "NIFTY", "15m", "context")
    assert tried == ["test/default-550b", "test/fallback-120b"] and result.model == "test/fallback-120b"
    assert result.warnings[0].startswith("retried on test/fallback-120b after test/default-550b (APITimeoutError)")
    assert models.active_model() == "test/fallback-120b"


def test_code_errors_and_second_failures_are_not_retried(monkeypatch):
    models = _two_model_manager(monkeypatch)
    adapter = TradingAgentsAdapter(make_env(), models)
    tried: list[str] = []

    def broken(agent, symbol, timeframe, context, model, deadline, started):
        tried.append(model)
        raise KeyError("bug in analyst")

    monkeypatch.setattr(adapter, "_run_once", broken)
    with pytest.raises(KeyError):
        adapter.run_analyst("market", "NIFTY", "15m", "context")
    assert tried == ["test/default-550b"]

    tried.clear()

    def always_overloaded(agent, symbol, timeframe, context, model, deadline, started):
        tried.append(model)
        raise ValueError("Provider returned error: {'code': 502, 'message': 'overloaded'}")

    monkeypatch.setattr(adapter, "_run_once", always_overloaded)
    with pytest.raises(ValueError):
        adapter.run_analyst("market", "NIFTY", "15m", "context")
    assert tried == ["test/default-550b", "test/fallback-120b"]  # exactly one retry, then the error surfaces


class _ScriptedModels:
    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.conversations: list[list[dict]] = []

    def chat(self, messages, **kwargs):
        self.conversations.append(list(messages))
        return LLMReply(self.replies.pop(0), "fake-model", 1.0)


REPORT = "NIFTY closed at 23,398.10; RSI 27.22; lower Bollinger band 23,390.00 acts as support; ATR 177.31."


def test_extraction_tolerates_fences_and_trailing_commas():
    reply = '```json\n{"signal": "BEARISH", "confidence": 62, "reasoning": "Below all averages.", "key_levels": [{"price": 23390.0, "type": "support", "note": "BB lower",},], "risks": ["oversold bounce"], "data_sources": ["verified snapshot"],}\n```'
    models = _ScriptedModels([reply])
    view, warnings = TradingAgentsAdapter(make_env(), models).extract("Market Analyst", REPORT)  # type: ignore[arg-type]
    assert view is not None and view.signal == "BEARISH" and [lvl.price for lvl in view.key_levels] == [23390.0]
    assert warnings == [] and len(models.conversations) == 1


def test_extraction_retries_once_with_the_parse_error_and_filters_invented_levels():
    broken = '{"signal": "BEARISH" "confidence": 62}'
    fixed = '{"signal": "BEARISH", "confidence": 62, "reasoning": "Weak trend.", "key_levels": [{"price": 23390, "type": "support"}, {"price": 22000, "type": "support"}], "risks": [], "data_sources": []}'
    models = _ScriptedModels([broken, fixed])
    view, warnings = TradingAgentsAdapter(make_env(), models).extract("Market Analyst", REPORT)  # type: ignore[arg-type]
    assert view is not None and [lvl.price for lvl in view.key_levels] == [23390.0]
    assert warnings[0].startswith("extraction attempt 1 invalid") and any("22000" in w for w in warnings)
    retry_prompt = models.conversations[1][-1]["content"]
    assert "not valid JSON" in retry_prompt and models.conversations[1][-2]["content"] == broken
    assert TradingAgentsAdapter(make_env(), _ScriptedModels(["nope", "still nope"])).extract("Market Analyst", REPORT)[0] is None  # type: ignore[arg-type]


class _RecordingModels:
    def __init__(self, text: str):
        self.text = text
        self.prompts: list[str] = []

    def chat(self, messages, **kwargs):
        self.prompts.append(messages[0]["content"])
        return LLMReply(self.text, "fake-model", 1.0)


def test_capped_analyst_report_is_finalised_from_tool_outputs_only():
    models = _RecordingModels("NIFTY closed at 23398.1 with RSI 49.3; a guessed target of 99999.")
    adapter = TradingAgentsAdapter(make_env(), models)  # type: ignore[arg-type]
    messages = [
        AIMessage(content="", tool_calls=[{"name": "get_stock_data", "args": {"symbol": "NIFTY"}, "id": "call-1"}]),
        ToolMessage(content="2026-09-11 close 23398.1, RSI 49.3", tool_call_id="call-1"),
    ]
    text, unknown = adapter._finalise_report("Market Analyst", "NIFTY", messages)
    assert "2026-09-11 close 23398.1, RSI 49.3" in models.prompts[0] and "ONLY these outputs" in models.prompts[0]
    assert text.startswith("NIFTY closed") and unknown == [99999.0]
    assert adapter._finalise_report("Market Analyst", "NIFTY", [AIMessage(content="thinking")]) == ("", [])
    assert len(models.prompts) == 1  # no tool outputs → no model call


def test_adapter_limits_upstream_retries_without_overriding_user_value(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_UPSTREAM_RETRIES", raising=False)
    TradingAgentsAdapter(make_env(), ModelManager(make_env(), Database(":memory:")))
    assert os.environ["TRADINGAGENTS_UPSTREAM_RETRIES"] == "1"
    monkeypatch.setenv("TRADINGAGENTS_UPSTREAM_RETRIES", "3")
    TradingAgentsAdapter(make_env(), ModelManager(make_env(), Database(":memory:")))
    assert os.environ["TRADINGAGENTS_UPSTREAM_RETRIES"] == "3"
