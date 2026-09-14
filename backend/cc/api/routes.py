"""REST endpoints. Handlers are synchronous (FastAPI runs them in a worker pool) because providers block."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..agents.assistant import ChatIn
from ..agents.schema import AGENTS
from ..analysis.backtest import BacktestParams
from ..analysis.hedging import HedgeRequest
from ..analysis.scanner import PRESETS
from ..analysis.signal_engine import DISCLAIMER
from ..analysis.strategies import TEMPLATES
from ..config import PROJECT_ROOT, TIMEFRAMES
from ..data.models import DataUnavailable, now_ist
from ..data.symbols import INDEX_TABLE
from ..orchestration.stocks import UNIVERSES
from ..services.alerts import AlertIn
from ..services.paper import PaperOrderIn
from .container import Services
from .security import respond

router = APIRouter(prefix="/api")

MAIN_INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "INDIAVIX"]
SECTOR_INDICES = ["NIFTYIT", "NIFTYPHARMA", "NIFTYAUTO", "NIFTYFMCG", "NIFTYMETAL", "NIFTYREALTY", "NIFTYENERGY",
                  "NIFTYPSUBANK", "NIFTYPVTBANK", "NIFTYMEDIA", "NIFTYINFRA", "NIFTYMIDCAP100", "NIFTYSMALLCAP100"]


def S(request: Request) -> Services:
    return request.app.state.services


def _client(request: Request) -> str:
    return request.client.host if request.client else "local"


def _limit(request: Request, bucket: str, limit: int, window: float) -> None:
    S(request).limiter.check(_client(request), bucket, limit, window)


def _tf(timeframe: str) -> str:
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"timeframe must be one of {', '.join(TIMEFRAMES)}")
    return timeframe


def _sym(request: Request, symbol: str) -> str:
    return S(request).registry.normalize(symbol)


# ---------------------------------------------------------------------------- status & settings
@router.get("/status")
def status(request: Request):
    s = S(request)
    settings = s.settings_store.get()
    ai = s.models.status()
    return respond({
        "app": {"name": "DalalSight", "version": __version__, "started_at": s.started_at.isoformat(), "now": now_ist().isoformat()},
        "market": s.analysis.market_status().to_dict(),
        "ai": {k: ai[k] for k in ("status", "active_model", "last_model_used", "calls_today", "daily_budget", "budget_left", "key_configured", "models", "last_error")},
        "provider": {"name": s.provider.label, "status": s.provider.health().status},
        "execution": {"mode": settings.execution_mode, "live_execution_enabled": s.env.live_execution_enabled},
        "monitor": s.monitor.status(),
        "replay": s.replay.status(),
    })


@router.get("/config")
def config(request: Request):
    s = S(request)
    return respond({
        "public": s.env.public(),
        "timeframes": TIMEFRAMES,
        "strategy_templates": {k: {"name": v["name"], "view": v["view"], "risk": v["risk"], "default_width": v["width"]} for k, v in TEMPLATES.items()},
        "scanner_presets": {k: {"name": v[0], "description": v[1]} for k, v in PRESETS.items()},
        "universes": UNIVERSES,
        "agents": AGENTS,
        "indices": {k: {"name": v.name, "tradingview": v.tradingview, "options": v.options} for k, v in INDEX_TABLE.items()},
        "disclaimer": DISCLAIMER,
    })


@router.get("/settings")
def get_settings(request: Request):
    return respond(S(request).settings_store.get().model_dump())


@router.put("/settings")
def put_settings(request: Request, patch: dict):
    s = S(request)
    settings = s.settings_store.update(patch)
    s.timeline.add("settings", f"Settings updated: {', '.join(sorted(patch))}")
    s.monitor.trigger()
    return respond(settings.model_dump())


@router.post("/settings/reset")
def reset_settings(request: Request):
    s = S(request)
    settings = s.settings_store.reset()
    s.timeline.add("settings", "Settings reset to defaults")
    return respond(settings.model_dump())


# ---------------------------------------------------------------------------- market data
@router.get("/symbols/search")
def search(request: Request, q: str = Query(min_length=1, max_length=40)):
    return respond(S(request).registry.search(q))


@router.get("/instrument/{symbol}")
def instrument(request: Request, symbol: str):
    s = S(request)
    return respond(s.registry.meta(s.registry.validate(symbol)).to_dict())


@router.get("/quotes")
def quotes(request: Request, symbols: str = Query(min_length=1, max_length=800)):
    s = S(request)
    names = [s.registry.normalize(x) for x in symbols.split(",") if x.strip()][:60]
    result = s.provider.get_quotes(names)
    return respond({k: (v.to_dict() if not isinstance(v, DataUnavailable) else v.to_dict()) for k, v in result.items()})


@router.get("/overview")
def overview(request: Request):
    s = S(request)
    quotes = s.provider.get_quotes(MAIN_INDICES + SECTOR_INDICES)

    def pack(symbol: str) -> dict:
        q = quotes.get(symbol)
        base = {"symbol": symbol, "name": INDEX_TABLE[symbol].name, "tradingview": INDEX_TABLE[symbol].tradingview}
        return {**base, **(q.to_dict() if q is not None and not isinstance(q, DataUnavailable) else {"unavailable": q.to_dict() if q else None})}

    breadth = None
    nse = getattr(s.provider, "nse", None)
    if nse is not None:
        try:
            data = nse.all_indices()
            breadth = {**data["breadth"], "timestamp": data["timestamp"].isoformat(), "source": nse.label}
        except DataUnavailable as exc:
            breadth = exc.to_dict()
    snapshots = {
        f"{sym}:{tf}": {"symbol": sym, "timeframe": tf, "label": snap["signal"]["label"], "bullish_pct": snap["signal"]["bullish_pct"],
                        "model_confidence": snap["signal"]["model_confidence"], "direction": snap["signal"]["direction"],
                        "regime": snap["regime"]["label"], "regime_code": snap["regime"]["code"], "regime_direction": snap["regime"]["direction"],
                        "price": snap["price"], "generated_at": snap["generated_at"]}
        for (sym, tf), snap in list(s.analysis.latest.items())
    }
    sectors = sorted((pack(x) for x in SECTOR_INDICES), key=lambda r: -(r.get("change_pct") or -999))
    return respond({"market": s.analysis.market_status().to_dict(), "indices": [pack(x) for x in MAIN_INDICES], "sectors": sectors,
                    "breadth": breadth, "snapshots": snapshots, "generated_at": now_ist().isoformat()})


@router.get("/chart/{symbol}")
def chart(request: Request, symbol: str, timeframe: str = "5m", bars: int = Query(500, ge=50, le=2000)):
    _limit(request, "chart", 240, 60)
    return respond(S(request).analysis.chart(_sym(request, symbol), _tf(timeframe), bars))


@router.get("/analysis/{symbol}")
def analysis(request: Request, symbol: str, timeframe: str = "5m", include_options: bool = True):
    _limit(request, "analysis", 120, 60)
    return respond(S(request).analysis.snapshot(_sym(request, symbol), _tf(timeframe), include_options=include_options))


# ---------------------------------------------------------------------------- options
@router.get("/options/{symbol}/expiries")
def expiries(request: Request, symbol: str):
    return respond([d.isoformat() for d in S(request).options.expiries(_sym(request, symbol))])


@router.get("/options/{symbol}/chain")
def option_chain(request: Request, symbol: str, expiry: str | None = None):
    _limit(request, "options", 60, 60)
    return respond(S(request).options.summary(_sym(request, symbol), expiry))


@router.get("/options/{symbol}/recommendations")
def option_recommendations(request: Request, symbol: str, expiry: str | None = None, timeframe: str = "15m"):
    _limit(request, "options", 60, 60)
    return respond(S(request).options.recommendations(_sym(request, symbol), expiry, _tf(timeframe)))


class LegIn(BaseModel):
    option_type: Literal["CE", "PE"]
    side: Literal[1, -1]
    strike: float = Field(gt=0)
    lots: int = Field(1, ge=1, le=100)


class StrategyBuildIn(BaseModel):
    symbol: str = Field(max_length=32)
    expiry: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    template: str | None = Field(None, max_length=40)
    legs: list[LegIn] | None = Field(None, max_length=8)
    lots: int = Field(1, ge=1, le=100)
    width_steps: int | None = Field(None, ge=1, le=40)


@router.post("/strategies/build")
def build_strategy(request: Request, body: StrategyBuildIn):
    _limit(request, "strategies", 60, 60)
    legs = [leg.model_dump() for leg in body.legs] if body.legs else None
    return respond(S(request).options.build_strategy(_sym(request, body.symbol), body.expiry, body.template, legs, body.lots, body.width_steps))


@router.get("/strategies/suggest")
def suggest_strategies(request: Request, symbol: str = "NIFTY", expiry: str | None = None, timeframe: str = "15m"):
    _limit(request, "strategies", 30, 60)
    return respond(S(request).options.suggest(_sym(request, symbol), expiry, _tf(timeframe)))


@router.post("/hedging/analyze")
def hedging(request: Request, body: HedgeRequest):
    _limit(request, "hedging", 20, 60)
    return respond(S(request).stocks.hedge(body))


# ---------------------------------------------------------------------------- stocks & scanner
class ScanIn(BaseModel):
    universe: Literal["NIFTY 50", "NIFTY 100", "NIFTY NEXT 50", "FNO", "WATCHLIST"] = "NIFTY 50"
    preset: str | None = Field(None, max_length=40)
    limit: int = Field(50, ge=1, le=250)


@router.post("/scanner/run")
def scan(request: Request, body: ScanIn):
    _limit(request, "scanner", 6, 60)
    if body.preset and body.preset not in PRESETS:
        raise ValueError(f"unknown preset {body.preset}")
    return respond(S(request).stocks.scan(body.universe, body.preset, body.limit))


@router.get("/stocks/{symbol}")
def stock(request: Request, symbol: str):
    _limit(request, "stocks", 30, 60)
    s = S(request)
    return respond(s.stocks.analyze(s.registry.validate(symbol)))


# ---------------------------------------------------------------------------- agents, commentary, assistant
AnalystName = Literal["market", "social", "news", "fundamentals", "derivatives"]


def _default_agents() -> list[AnalystName]:
    return ["market"]


class AgentRunIn(BaseModel):
    symbol: str = Field("NIFTY", max_length=32)
    timeframe: str = "15m"
    agents: list[AnalystName] = Field(default_factory=_default_agents, min_length=1, max_length=5)
    kind: Literal["analysts", "full_pipeline"] = "analysts"


@router.get("/agents/meta")
def agents_meta(request: Request):
    s = S(request)
    return respond({"agents": AGENTS, "budget_left": s.models.budget_left(), "daily_budget": s.env.ai_daily_call_budget,
                    "active_run": s.orchestrator.active_run, "weights": s.settings_store.get().agents.agent_weights})


@router.post("/agents/run")
def run_agents(request: Request, body: AgentRunIn):
    _limit(request, "agents", 10, 3600)
    s = S(request)
    symbol = s.registry.validate(body.symbol)
    needed = sum(AGENTS[a]["est_calls"] + 1 for a in body.agents) if body.kind == "analysts" else 30
    s.models.ensure_ready(needed)
    try:
        run_id = s.orchestrator.start(symbol, _tf(body.timeframe), list(dict.fromkeys(body.agents)), body.kind)
    except RuntimeError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    return respond({"run_id": run_id, "estimated_calls": needed}, 202)


@router.get("/agents/runs")
def agent_runs(request: Request, symbol: str | None = None, limit: int = Query(30, ge=1, le=200)):
    return respond(S(request).orchestrator.list(limit, _sym(request, symbol) if symbol else None))


@router.get("/agents/runs/{run_id}")
def agent_run(request: Request, run_id: int):
    row = S(request).orchestrator.get(run_id)
    if not row:
        raise HTTPException(404, detail="run not found")
    return respond(row)


@router.get("/commentary")
def commentary(request: Request, symbol: str | None = None, mode: Literal["live", "replay"] | None = None,
               limit: int = Query(100, ge=1, le=500)):
    return respond(S(request).commentary.recent(limit, _sym(request, symbol) if symbol else None, mode))


@router.post("/assistant/chat")
def chat(request: Request, body: ChatIn):
    _limit(request, "assistant", 30, 60)
    return respond(S(request).assistant.answer(body))


@router.get("/assistant/history")
def chat_history(request: Request, session: str = Query("default", pattern=r"^[A-Za-z0-9_-]{1,64}$")):
    return respond(S(request).assistant.history(session))


# ---------------------------------------------------------------------------- alerts & signals
@router.get("/alerts")
def list_alerts(request: Request):
    return respond(S(request).alerts.all())


@router.post("/alerts")
def create_alert(request: Request, body: AlertIn):
    s = S(request)
    alert = s.alerts.create(body)
    s.timeline.add("alerts", f"Alert created: {body.name}", body.rule.symbol)
    return respond(alert, 201)


@router.put("/alerts/{alert_id}")
def update_alert(request: Request, alert_id: int, body: AlertIn):
    alert = S(request).alerts.update(alert_id, body)
    if not alert:
        raise HTTPException(404, detail="alert not found")
    return respond(alert)


@router.delete("/alerts/{alert_id}")
def delete_alert(request: Request, alert_id: int):
    if not S(request).alerts.delete(alert_id):
        raise HTTPException(404, detail="alert not found")
    return respond({"deleted": alert_id})


@router.get("/alerts/events")
def alert_events(request: Request, limit: int = Query(200, ge=1, le=1000)):
    return respond(S(request).alerts.events(limit))


class AlertTestIn(BaseModel):
    channels: list[Literal["dashboard", "browser", "sound", "voice", "telegram", "email", "webhook"]] = Field(min_length=1)


@router.post("/alerts/test")
def test_alert(request: Request, body: AlertTestIn):
    _limit(request, "alert_test", 5, 60)
    return respond(S(request).alerts.test(body.channels))


@router.get("/signals")
def signals(request: Request, symbol: str | None = None, status: Literal["open", "closed"] | None = None,
            limit: int = Query(200, ge=1, le=1000)):
    return respond(S(request).signals.list(limit, _sym(request, symbol) if symbol else None, status))


@router.get("/signals/history/{symbol}")
def signal_history(request: Request, symbol: str, timeframe: str = "5m", bars: int = Query(250, ge=20, le=600)):
    """BUY/SELL markers for the chart: the engine's signal rebuilt at each recent bar close (no look-ahead)."""
    _limit(request, "signal_history", 60, 60)
    return respond(S(request).analysis.signal_history(_sym(request, symbol), _tf(timeframe), bars))


@router.get("/signals/stats")
def signal_stats(request: Request):
    return respond(S(request).signals.stats())


@router.post("/signals/evaluate")
def evaluate_signals(request: Request):
    _limit(request, "evaluate", 6, 60)
    return respond({"closed": S(request).signals.evaluate_open()})


# ---------------------------------------------------------------------------- paper trading & backtests
@router.get("/paper/orders")
def paper_orders(request: Request):
    return respond(S(request).paper.orders())


@router.post("/paper/orders")
def paper_order(request: Request, body: PaperOrderIn):
    _limit(request, "paper", 30, 60)
    return respond(S(request).paper.place(body), 201)


@router.get("/paper/positions")
def paper_positions(request: Request):
    return respond(S(request).paper.positions())


@router.post("/backtest")
def start_backtest(request: Request, body: BacktestParams):
    _limit(request, "backtest", 6, 600)
    s = S(request)
    body.symbol = s.registry.validate(body.symbol)
    _tf(body.timeframe)
    try:
        job_id = s.backtests.start(body)
    except RuntimeError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    return respond({"id": job_id}, 202)


@router.get("/backtest")
def list_backtests(request: Request):
    return respond(S(request).backtests.list())


@router.get("/backtest/{job_id}")
def get_backtest(request: Request, job_id: int):
    row = S(request).backtests.get(job_id)
    if not row:
        raise HTTPException(404, detail="backtest not found")
    return respond(row)


@router.get("/calibration/{symbol}")
def calibration(request: Request, symbol: str, timeframe: str = "5m"):
    """How the engine's stated bullish % held up in the newest backtest of this symbol and timeframe."""
    symbol, timeframe = _sym(request, symbol), _tf(timeframe)
    result = S(request).backtests.latest_calibration(symbol, timeframe)
    if result is None:
        return respond({"available": False, "symbol": symbol, "timeframe": timeframe,
                        "reason": f"no completed backtest with calibration for {symbol} {timeframe}; run one in Signals → Backtest"})
    return respond({"available": True, "symbol": symbol, "timeframe": timeframe, **result})


# ---------------------------------------------------------------------------- timeline, health, replay, monitor
@router.get("/timeline")
def timeline(request: Request, kind: str | None = Query(None, max_length=30), symbol: str | None = None,
             limit: int = Query(200, ge=1, le=1000)):
    return respond(S(request).timeline.recent(limit, kind, _sym(request, symbol) if symbol else None))


@router.get("/errors")
def errors(request: Request, limit: int = Query(100, ge=1, le=500)):
    return respond(S(request).timeline.errors(limit))


@router.get("/health")
def health(request: Request):
    return respond(S(request).health.report())


class ReplayIn(BaseModel):
    symbol: str = Field("NIFTY", max_length=32)
    timeframe: Literal["1m", "3m", "5m", "15m"] = "5m"
    session_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    interval_seconds: float = Field(1.0, ge=0.1, le=10)


@router.post("/replay/start")
def replay_start(request: Request, body: ReplayIn):
    _limit(request, "replay", 10, 60)
    s = S(request)
    try:
        return respond(s.replay.start(s.registry.validate(body.symbol), body.timeframe, body.session_date, body.interval_seconds))
    except RuntimeError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@router.post("/replay/stop")
def replay_stop(request: Request):
    return respond(S(request).replay.stop())


@router.get("/replay/status")
def replay_status(request: Request):
    return respond(S(request).replay.status())


@router.post("/monitor/refresh")
def monitor_refresh(request: Request):
    _limit(request, "refresh", 12, 60)
    S(request).monitor.trigger()
    return respond({"triggered": True})


# ---------------------------------------------------------------------------- TradingView
PINE_SCRIPT = PROJECT_ROOT / "tradingview" / "dalalsight_signal_engine.pine"


@router.get("/tradingview/pine")
def tradingview_pine():
    """The signal engine as a Pine Script indicator for the user's own TradingView app."""
    if not PINE_SCRIPT.is_file():
        raise HTTPException(404, detail="Pine Script file not found")
    return PlainTextResponse(PINE_SCRIPT.read_text(encoding="utf-8"), media_type="text/plain; charset=utf-8")
