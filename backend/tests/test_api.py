import base64
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from helpers import SECRET, FakeAdapter, make_env
from starlette.websockets import WebSocketDisconnect

from cc.analysis.signal_engine import (
    LABEL_BEAR,
    LABEL_BULL,
    LABEL_HIGH_RISK,
    LABEL_LOW_QUALITY,
    LABEL_NO_TRADE,
)
from cc.api.app import create_app
from cc.api.container import build_services
from cc.data.brokers import BrokerFeedProvider
from cc.data.models import DataUnavailable
from cc.storage.db import Database

LABELS = {LABEL_BULL, LABEL_BEAR, LABEL_HIGH_RISK, LABEL_LOW_QUALITY, LABEL_NO_TRADE, "WATCH"}


def wait_for(fn, timeout: float = 60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("condition not met in time")


def test_status_config_health_never_expose_secrets(client, monkeypatch):
    monkeypatch.setenv("CC_TEST_AI_KEY", SECRET)
    for path in ("/api/status", "/api/config", "/api/health", "/api/settings", "/api/agents/meta"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert SECRET not in response.text
    assert client.get("/api/config").json()["public"]["ai_key_configured"] is True
    assert client.get("/api/status").json()["execution"] == {"mode": "analysis", "live_execution_enabled": False}


def test_analysis_and_chart(client):
    body = client.get("/api/analysis/NIFTY?timeframe=5m").json()
    assert body["signal"]["label"] in LABELS and len(body["signal"]["components"]) == 8
    assert body["options"]["expiry"] and body["provenance"]["provider"] == "Fake test provider"
    assert "Model-estimated" in body["signal"]["disclaimer"]
    chart = client.get("/api/chart/nifty?timeframe=15m&bars=100").json()
    times = [c["time"] for c in chart["candles"]]
    assert len(times) == 100 and times == sorted(times)
    assert times[-1] == int(pd.Timestamp(chart["provenance"]["last_bar"]).timestamp()) + 19800  # IST wall-clock seconds
    assert times[-1] - times[-2] == 15 * 60
    assert chart["indicators"]["ema_fast"] and chart["levels"]["levels"]


def test_signal_history_gives_chart_markers(client):
    body = client.get("/api/signals/history/NIFTY?timeframe=5m&bars=120").json()
    assert body["bars"] == 120 and body["latest"]["label"] in LABELS
    candle_times = {c["time"] for c in client.get("/api/chart/NIFTY?timeframe=5m&bars=300").json()["candles"]}
    for marker in body["markers"]:
        assert marker["time"] in candle_times and marker["side"] in ("BUY", "SELL")
        assert marker["label"] in (LABEL_BULL, LABEL_BEAR, LABEL_HIGH_RISK)
    assert client.get("/api/signals/history/NIFTY?timeframe=5m&bars=120").json()["markers"] == body["markers"]  # cached


def test_invalid_inputs_are_rejected(client):
    assert client.get("/api/analysis/NIFTY?timeframe=2m").status_code == 422
    assert client.get("/api/analysis/NI$FTY").status_code == 422
    assert client.get("/api/chart/NIFTY?bars=5").status_code == 422
    assert client.put("/api/settings", json={"signal": {"ema_fast": 50, "ema_slow": 20}}).status_code == 422
    assert client.post("/api/scanner/run", json={"universe": "EVERYTHING"}).status_code == 422
    assert client.post("/api/alerts", json={"name": "x", "rule": {"type": "price_above", "symbol": "NIFTY"}}).status_code == 422


def test_settings_update_persists(client, services):
    response = client.put("/api/settings", json={"signal": {"weights": {"trend": 30}}, "watchlist": ["NIFTY", "INFY"]})
    assert response.status_code == 200
    assert services.settings_store.get().signal.weights.trend == 30
    assert client.get("/api/settings").json()["watchlist"] == ["NIFTY", "INFY"]


def test_option_and_strategy_endpoints(client):
    expiries = client.get("/api/options/NIFTY/expiries").json()
    assert len(expiries) == 2
    chain = client.get(f"/api/options/NIFTY/chain?expiry={expiries[0]}").json()
    assert chain["atm_strike"] and chain["table"] and chain["lot_size"] == 65
    assert client.get("/api/options/NIFTY/chain?expiry=2020-01-01").status_code == 422
    unavailable = client.get("/api/options/TCS/expiries")
    assert unavailable.status_code == 503 and unavailable.json()["detail"]["status"] == "unavailable"
    strategy = client.post("/api/strategies/build", json={"symbol": "NIFTY", "template": "iron_condor"}).json()
    assert len(strategy["legs"]) == 4 and strategy["probability_of_profit"] is not None
    custom = client.post("/api/strategies/build", json={"symbol": "NIFTY", "legs": [
        {"option_type": "CE", "side": 1, "strike": chain["atm_strike"], "lots": 1}]}).json()
    assert custom["max_profit"] == "unlimited"
    recommendations = client.get("/api/options/NIFTY/recommendations?timeframe=15m").json()
    assert recommendations["signal"]["label"] in LABELS
    assert client.get("/api/strategies/suggest?symbol=NIFTY").status_code == 200


def test_paper_trading_is_guarded(client):
    order = {"symbol": "NIFTY", "side": "BUY", "quantity": 65}
    refused = client.post("/api/paper/orders", json=order)
    assert refused.status_code == 403 and "ANALYSIS" in refused.json()["detail"]
    client.put("/api/settings", json={"execution_mode": "live"})
    live = client.post("/api/paper/orders", json=order)
    assert live.status_code == 403 and "disabled" in live.json()["detail"]
    client.put("/api/settings", json={"execution_mode": "paper"})
    filled = client.post("/api/paper/orders", json=order)
    assert filled.status_code == 201 and filled.json()["mode"] == "PAPER"
    position = client.get("/api/paper/positions").json()[0]
    assert position["quantity"] == 65 and position["mark"] is not None


def test_paper_average_price_and_realized_pnl(services):
    services.settings_store.update({"execution_mode": "paper"})
    prices = iter([100.0, 110.0, 120.0, 90.0])
    services.paper.price = lambda instrument: (next(prices, 95.0), "test")
    from cc.services.paper import PaperOrderIn

    for side, qty in (("BUY", 10), ("BUY", 10), ("SELL", 15), ("SELL", 10)):
        services.paper.place(PaperOrderIn(symbol="INFY", side=side, quantity=qty))
    position = services.paper.positions()[0]
    assert position["realized_pnl"] == pytest.approx(15 * 15 - 5 * 15)
    assert position["quantity"] == -5 and position["avg_price"] == 90.0


def test_assistant_resolves_context_and_falls_back_to_engine(client):
    body = client.post("/api/assistant/chat", json={"question": "What is the BANKNIFTY setup on 15 min?",
                                                    "context": {"symbol": "NIFTY", "timeframe": "5m"}}).json()
    assert body["context"]["symbol"] == "BANKNIFTY" and body["context"]["timeframe"] == "15m"
    assert body["source"].startswith("engine (AI unavailable")
    assert "1. Direct answer" in body["answer"] and "9. Confidence and data limitations" in body["answer"]
    strike = client.post("/api/assistant/chat", json={"question": "Is the 23500 CE worth it?"}).json()
    assert strike["context"]["strike"] == 23500 and strike["context"]["option_type"] == "CE"
    assert len(client.get("/api/assistant/history?session=default").json()) == 4


def test_agent_run_requires_ai_key(client):
    response = client.post("/api/agents/run", json={"symbol": "NIFTY", "agents": ["market"]})
    assert response.status_code == 503 and "not configured" in response.json()["detail"]["reason"]


def test_alert_crud(client):
    created = client.post("/api/alerts", json={"name": "Nifty 24k", "rule": {"type": "price_above", "symbol": "nifty", "value": 24000},
                                               "channels": ["dashboard", "sound"]})
    assert created.status_code == 201 and created.json()["rule"]["symbol"] == "NIFTY"
    alert_id = created.json()["id"]
    updated = client.put(f"/api/alerts/{alert_id}", json={"name": "Nifty 24.1k", "rule": {"type": "price_above", "symbol": "NIFTY", "value": 24100}})
    assert updated.json()["name"] == "Nifty 24.1k"
    assert client.delete(f"/api/alerts/{alert_id}").status_code == 200
    assert client.delete(f"/api/alerts/{alert_id}").status_code == 404


def test_rate_limit(client):
    statuses = [client.post("/api/alerts/test", json={"channels": ["dashboard"]}).status_code for _ in range(6)]
    assert statuses[:5] == [200] * 5 and statuses[5] == 429


def test_backtest_and_replay_jobs(client, services):
    job = client.post("/api/backtest", json={"symbol": "NIFTY", "timeframe": "5m", "bars": 400, "warmup": 120, "window": 150})
    assert job.status_code == 202
    done = wait_for(lambda: (lambda row: row if row["status"] != "running" else None)(client.get(f"/api/backtest/{job.json()['id']}").json()))
    assert done["status"] == "completed", done.get("error")
    calibration = client.get("/api/calibration/NIFTY?timeframe=5m").json()
    assert calibration["available"] and calibration["backtest_id"] == job.json()["id"] and len(calibration["by_bullish_pct"]) == 6
    assert client.get("/api/calibration/NIFTY?timeframe=1h").json()["available"] is False
    started = client.post("/api/replay/start", json={"symbol": "NIFTY", "timeframe": "5m", "interval_seconds": 0.1})
    assert started.status_code == 200 and started.json()["running"]
    wait_for(lambda: client.get("/api/replay/status").json().get("processed", 0) >= 2)
    client.post("/api/replay/stop")
    wait_for(lambda: not client.get("/api/replay/status").json()["running"])


def test_websocket_push(client, services):
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        services.bus.publish("timeline", {"message": "hello from test"})
        message = ws.receive_json()
        assert message["type"] == "timeline" and message["data"]["message"] == "hello from test"


def test_access_token_protects_api_and_websocket(registry, provider):
    services = build_services(make_env(access_token="tok-123"), db=Database(":memory:"), provider=provider, registry=registry,
                              adapter_factory=FakeAdapter)
    with TestClient(create_app(services=services, start_background=False)) as c:
        assert c.get("/api/status").status_code == 401
        assert c.get("/api/status", headers={"X-Access-Token": "tok-123"}).status_code == 200
        assert c.get("/api/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
        for path in ("/api/docs", "/api/openapi.json"):
            assert c.get(path).status_code == 401, path
            assert c.get(path, headers={"X-Access-Token": "tok-123"}).status_code == 200, path
        with pytest.raises(WebSocketDisconnect), c.websocket_connect("/ws") as ws:
            ws.receive_json()
        protocol = "cc-token." + base64.urlsafe_b64encode(b"tok-123").decode().rstrip("=")
        with c.websocket_connect("/ws", subprotocols=[protocol]) as ws:
            assert ws.receive_json()["type"] == "hello"


def test_broker_provider_reports_required_credentials(registry):
    broker = BrokerFeedProvider("kite", registry)
    with pytest.raises(DataUnavailable) as info:
        broker.get_quote("NIFTY")
    assert "MARKET_DATA_API_KEY" in info.value.requirement and "credentials not configured" in info.value.reason
    assert broker.health().status == "NOT_CONFIGURED"


def test_dashboard_html_is_never_served_stale(client):
    from cc.api.app import DIST

    if not (DIST / "index.html").is_file():
        pytest.skip("web/dist not built")
    for path in ("/", "/watchlist"):
        response = client.get(path)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-cache"
    bundle = next((DIST / "assets").glob("*.js"))
    assert "immutable" in client.get(f"/assets/{bundle.name}").headers["cache-control"]


def test_tradingview_pine_script_is_served(client):
    response = client.get("/api/tradingview/pine")
    assert response.status_code == 200 and response.text.startswith("//@version=6")
    assert 'indicator("DalalSight Signal Engine"' in response.text and "alertcondition(" in response.text


def test_cors_lets_a_separately_hosted_dashboard_use_the_token(registry, provider):
    origin = "https://cc-dashboard.vercel.app"
    services = build_services(make_env(access_token="tok-123", cors_origins=(origin,)), db=Database(":memory:"),
                              provider=provider, registry=registry, adapter_factory=FakeAdapter)
    with TestClient(create_app(services=services, start_background=False)) as c:
        preflight = c.options("/api/status", headers={"Origin": origin, "Access-Control-Request-Method": "GET",
                                                      "Access-Control-Request-Headers": "x-access-token"})
        assert preflight.status_code == 200 and preflight.headers["access-control-allow-origin"] == origin
        refused = c.get("/api/status", headers={"Origin": origin})
        assert refused.status_code == 401 and refused.headers["access-control-allow-origin"] == origin
        allowed = c.get("/api/status", headers={"Origin": origin, "X-Access-Token": "tok-123"})
        assert allowed.status_code == 200 and allowed.headers["access-control-allow-origin"] == origin
        assert "access-control-allow-origin" not in c.get("/api/status", headers={"Origin": "https://evil.example"}).headers


def test_server_refuses_public_bind_without_token(monkeypatch):
    import cc.__main__ as entry

    started: list[dict] = []
    monkeypatch.setattr(entry, "load_environment", lambda: None)
    monkeypatch.setattr("cc.api.app.create_app", lambda env: object())
    monkeypatch.setattr(entry.uvicorn, "run", lambda app, **kwargs: started.append(kwargs))
    monkeypatch.setenv("CC_HOST", "0.0.0.0")
    monkeypatch.delenv("CC_ACCESS_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="CC_ACCESS_TOKEN"):
        entry.main()
    assert not started
    monkeypatch.setenv("CC_ACCESS_TOKEN", "a-long-random-token")
    monkeypatch.delenv("CC_PORT", raising=False)
    monkeypatch.setenv("PORT", "10000")
    entry.main()
    assert started[0]["host"] == "0.0.0.0" and started[0]["port"] == 10000
