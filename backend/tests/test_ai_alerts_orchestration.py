import json
import time

import pytest
from helpers import SECRET, FakeResponse, make_env
from pydantic import ValidationError

from cc.agents.commentary import CommentaryEngine
from cc.agents.llm import AIUnavailable, LLMReply, ModelManager, unverified_numbers
from cc.agents.schema import AgentResult
from cc.config import RuntimeSettings
from cc.data.models import now_ist
from cc.orchestration.orchestrator import NO_TRADE, compute_consensus
from cc.services.alerts import AlertIn, AlertRule, AlertService
from cc.services.bus import EventBus
from cc.storage.db import Database

# --------------------------------------------------------------------------- model manager


def test_unverified_numbers():
    facts = {"price": 23398.1, "support": 23300.0, "pct": 55.5, "changes": ["Bullish EMA 9/21 crossover"]}
    assert unverified_numbers("NIFTY at 23,398.10 above support 23300 with 55.5% bullish, EMA 9/21", facts) == []
    assert unverified_numbers("target 23,650 is next", facts) == [23650.0]
    assert unverified_numbers("on the 5m chart, 3 events", facts) == []


def manager(monkeypatch, models: set[str] | None = None, **env_overrides) -> ModelManager:
    monkeypatch.setenv("CC_TEST_AI_KEY", SECRET)
    mm = ModelManager(make_env(**env_overrides), Database(":memory:"))
    mm._models, mm._models_checked = models if models is not None else {"test/default-550b", "test/fallback-120b"}, time.time()
    return mm


def test_missing_key_is_reported():
    mm = ModelManager(make_env(), Database(":memory:"))
    with pytest.raises(AIUnavailable, match="not configured"):
        mm.chat([{"role": "user", "content": "hi"}])
    assert mm.status()["status"] == "NOT_CONFIGURED"


def test_overloaded_default_falls_back_and_cools_down(monkeypatch):
    mm = manager(monkeypatch)
    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append(json["model"])
        assert headers["Authorization"] == f"Bearer {SECRET}"
        if json["model"] == "test/default-550b":
            return FakeResponse(200, {"error": {"code": 502, "message": "Provider returned error: overloaded"}})
        return FakeResponse(200, {"choices": [{"message": {"content": "fallback answer"}}]})

    monkeypatch.setattr("cc.agents.llm.requests.post", fake_post)
    reply = mm.chat([{"role": "user", "content": "hi"}])
    assert reply.model == "test/fallback-120b" and reply.text == "fallback answer"
    assert calls == ["test/default-550b", "test/fallback-120b"]
    status = mm.status()
    assert status["active_model"] == "test/fallback-120b" and status["status"] == "DEGRADED"
    assert mm.calls_today() == 2
    assert SECRET not in json.dumps(status)


def test_unlisted_default_model_is_skipped(monkeypatch):
    mm = manager(monkeypatch, models={"test/fallback-120b"})
    monkeypatch.setattr("cc.agents.llm.requests.post",
                        lambda url, json, headers, timeout: FakeResponse(200, {"choices": [{"message": {"content": json["model"]}}]}))
    assert mm.chat([{"role": "user", "content": "hi"}]).model == "test/fallback-120b"
    default = next(m for m in mm.status()["models"] if m["role"] == "default")
    assert default["usable"] is False and default["state"] == "not listed by provider"


def test_budget_and_override(monkeypatch):
    mm = manager(monkeypatch, ai_daily_call_budget=1)
    mm.record_call(True)
    with pytest.raises(AIUnavailable, match="budget exhausted"):
        mm.chat([{"role": "user", "content": "hi"}])
    override = ModelManager(make_env(), Database(":memory:"), override=lambda: "test/override")
    assert override.configured_models()[0] == "test/override"


# --------------------------------------------------------------------------- commentary


class FakeModels:
    def __init__(self, text: str = "", error: Exception | None = None):
        self.text, self.error = text, error

    def chat(self, messages, **kwargs):
        if self.error:
            raise self.error
        return LLMReply(self.text, "fake-model", 1.0)


def snap(label="WATCH", regime="RANGE_BOUND", events=(), trading=True, bar="2026-09-11T10:00:00+05:30", confidence=40.0):
    return {
        "symbol": "NIFTY", "timeframe": "5m", "bar_time": bar, "price": 23400.0, "market": {"is_trading": trading},
        "signal": {"label": label, "bullish_pct": 55.0, "bearish_pct": 45.0, "model_confidence": confidence, "components": [], "plan": None},
        "regime": {"code": regime, "label": regime.replace("_", " ").title()},
        "levels": {"nearest_support": {"price": 23300.0, "label": "Swing low"}, "nearest_resistance": None},
        "events": list(events), "provenance": {"provider": "fake"},
    }


@pytest.fixture
def engine():
    clock = [1_000_000.0]
    commentary = CommentaryEngine(Database(":memory:"), FakeModels(), EventBus(), RuntimeSettings)
    commentary.clock = lambda: clock[0]
    commentary.test_clock = clock
    return commentary


def test_no_live_commentary_when_market_closed(engine):
    assert engine.process(snap(trading=False)) is None
    assert engine.process(snap(label="BULLISH SETUP", trading=False)) is None
    assert engine.process(snap(), mode="replay") is None
    assert engine.process(snap(label="BULLISH SETUP", trading=False), mode="replay")["mode"] == "replay"


def test_commentary_only_on_material_change(engine):
    assert engine.process(snap()) is None
    assert engine.process(snap()) is None
    entry = engine.process(snap(label="BULLISH SETUP"))
    assert entry and entry["priority"] == "HIGH" and "Signal changed from WATCH to BULLISH SETUP" in entry["text"]
    assert engine.recent(10)[0]["id"] == entry["id"]


def test_event_cooldown(engine):
    event = {"key": "breakout", "priority": "HIGH", "message": "Breakout above 20-bar high 23,450.00"}
    engine.process(snap())
    assert engine.process(snap(events=[event], bar="2026-09-11T10:05:00+05:30")) is not None
    engine.test_clock[0] += 60
    assert engine.process(snap(events=[event], bar="2026-09-11T10:10:00+05:30")) is None
    engine.test_clock[0] += 1000
    assert engine.process(snap(events=[event], bar="2026-09-11T10:15:00+05:30")) is not None


def test_ai_narration_rejected_when_it_invents_numbers(engine):
    engine.process(snap())
    entry = engine.process(snap(label="BULLISH SETUP"))
    engine.models = FakeModels("NIFTY looks strong and could reach 23,900 soon.")
    engine._narrate(entry)
    row = engine.recent(1)[0]
    assert row["text"] == entry["text"] and "rejected" in row["text_source"]
    engine.models = FakeModels("NIFTY at 23,400.00 turned to a bullish setup with support at 23,300.00.")
    engine._narrate(entry)
    assert engine.recent(1)[0]["text_source"] == "ai:fake-model"


# --------------------------------------------------------------------------- alerts


def alert_snap(price: float, label: str = "WATCH") -> dict:
    return {"symbol": "NIFTY", "timeframe": "5m", "price": price, "signal": {"label": label, "model_confidence": 40},
            "regime": {"code": "RANGE_BOUND", "label": "Range-bound"}, "options": None, "new_events": []}


def test_alert_rule_validation():
    with pytest.raises(ValidationError):
        AlertRule(type="price_above", symbol="NIFTY")
    with pytest.raises(ValidationError):
        AlertRule(type="event", symbol="NIFTY")
    with pytest.raises(ValidationError):
        AlertRule(type="price_above", symbol="BAD SYMBOL!", value=1)


def test_price_alert_edge_trigger_and_cooldown():
    service = AlertService(Database(":memory:"), make_env(), EventBus())
    service.create(AlertIn(name="NIFTY above", rule=AlertRule(type="price_above", symbol="NIFTY", value=23500), channels=["dashboard"],
                           cooldown_seconds=60))
    assert service.check(alert_snap(23400)) == []
    assert len(service.check(alert_snap(23510))) == 1
    assert service.check(alert_snap(23520)) == []
    service.check(alert_snap(23400))
    assert service.check(alert_snap(23600)) == []  # still inside cooldown
    assert len(service.events()) == 1


def test_unconfigured_external_channel_reports_failure():
    service = AlertService(Database(":memory:"), make_env(), EventBus())
    alert = service.create(AlertIn(name="Label", rule=AlertRule(type="signal_label", symbol="NIFTY", label="BULLISH SETUP"),
                                   channels=["dashboard", "telegram"]))
    service.check(alert_snap(23400))
    fired = service.check(alert_snap(23400, "BULLISH SETUP"))
    assert fired and fired[0]["alert_id"] == alert["id"]
    for _ in range(50):
        delivery = service.events()[0]["delivery"]
        if delivery["telegram"] != "pending":
            break
        time.sleep(0.05)
    assert delivery["dashboard"] == "sent to dashboard" and delivery["telegram"].startswith("failed: Telegram not configured")


# --------------------------------------------------------------------------- consensus & orchestration


def result(agent: str, signal: str, confidence: float, basis: str = "llm_assessed") -> AgentResult:
    return AgentResult(agent=agent, name=agent, timestamp=now_ist().isoformat(), symbol="NIFTY", timeframe="15m", signal=signal,
                       confidence=confidence, confidence_basis=basis, reasoning=f"{agent} reasoning")


def test_consensus_math_and_conflicts():
    consensus = compute_consensus([result("technical", "BULLISH", 60, "rule_based"), result("market", "BULLISH", 80),
                                   result("news", "BEARISH", 40)], {})
    assert consensus["score"] == pytest.approx(1.0 / 1.8, abs=1e-3)
    assert consensus["agreement_pct"] == pytest.approx(140 / 1.8, abs=0.1)
    assert consensus["signal"] == "BULLISH" and [c["agent"] for c in consensus["conflicts"]] == ["news"]


def test_consensus_requires_confirmation():
    gated = compute_consensus([result("technical", "NO_TRADE", 30, "rule_based"), result("market", "BULLISH", 90),
                               result("fundamentals", "BULLISH", 80)], {})
    assert gated["signal"] == NO_TRADE and gated["direction_view"] == "BULLISH"
    mixed = compute_consensus([result("market", "BULLISH", 70), result("news", "BEARISH", 70)], {})
    assert mixed["signal"] == NO_TRADE
    assert compute_consensus([result("market", "ERROR", 0)], {})["signal"] == NO_TRADE


def test_orchestrator_run_with_fake_adapter(services):
    run_id = services.orchestrator.start("NIFTY", "5m", ["market", "news"])
    for _ in range(200):
        row = services.orchestrator.get(run_id)
        if row["status"] != "running":
            break
        time.sleep(0.05)
    assert row["status"] == "completed", row.get("error")
    assert [r["agent"] for r in row["results"]] == ["technical", "market", "news"]
    assert row["consensus"]["signal"] and row["consensus"]["votes"]
    assert any(entry["kind"] == "agents" for entry in services.timeline.recent(20))
    assert services.orchestrator.latest_consensus("NIFTY")["run_id"] == run_id
