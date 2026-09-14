"""Service wiring. Tests pass their own provider/env/database; production uses the environment."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from ..agents.assistant import Assistant
from ..agents.commentary import CommentaryEngine
from ..agents.llm import ModelManager
from ..config import PROJECT_ROOT, EnvConfig
from ..data.brokers import build_provider
from ..data.cache import TTLCache
from ..data.models import now_ist
from ..data.provider import MarketDataProvider
from ..data.symbols import SymbolRegistry
from ..orchestration.analysis import AnalysisService, OptionsService
from ..orchestration.orchestrator import AgentOrchestrator, AnalystAdapter
from ..orchestration.stocks import StockService
from ..services.alerts import AlertService
from ..services.backtests import BacktestService
from ..services.bus import EventBus
from ..services.health import HealthService
from ..services.monitor import MonitorService
from ..services.paper import PaperService
from ..services.replay import ReplayService
from ..services.settings_store import SettingsStore
from ..services.signals import SignalService
from ..services.timeline import Timeline
from ..storage.db import Database
from .security import RateLimiter


@dataclass
class Services:
    env: EnvConfig
    db: Database
    bus: EventBus
    cache: TTLCache
    registry: SymbolRegistry
    provider: MarketDataProvider
    settings_store: SettingsStore
    timeline: Timeline
    models: ModelManager
    analysis: AnalysisService
    options: OptionsService
    stocks: StockService
    commentary: CommentaryEngine
    alerts: AlertService
    signals: SignalService
    paper: PaperService
    orchestrator: AgentOrchestrator
    assistant: Assistant
    monitor: MonitorService
    replay: ReplayService
    backtests: BacktestService
    health: HealthService
    limiter: RateLimiter
    started_at: datetime


def build_services(env: EnvConfig, *, db: Database | None = None, provider: MarketDataProvider | None = None,
                   registry: SymbolRegistry | None = None, adapter_factory: Callable[[], AnalystAdapter] | None = None) -> Services:
    db = db or Database(env.db_path)
    # Jobs run in worker threads; any still marked running belong to a previous process.
    db.execute("UPDATE agent_runs SET status = 'failed', finished_at = ?, error = 'interrupted: server restarted' WHERE status = 'running'",
               (now_ist().isoformat(),))
    db.execute("UPDATE backtests SET status = 'failed', error = 'interrupted: server restarted' WHERE status = 'running'")
    bus = EventBus()
    cache = TTLCache()
    registry = registry or SymbolRegistry(PROJECT_ROOT / "data" / "reference")
    settings_store = SettingsStore(db)
    settings = settings_store.get
    provider = provider or build_provider(env, registry, cache, lambda: settings().market_hours)
    timeline = Timeline(db, bus)
    models = ModelManager(env, db, override=lambda: settings().ai_model_override)
    analysis = AnalysisService(provider, registry, settings, cache, db)
    options = OptionsService(provider, registry, settings, cache, db, analysis)
    stocks = StockService(provider, registry, settings, cache, analysis, options)
    commentary = CommentaryEngine(db, models, bus, settings)
    alerts = AlertService(db, env, bus)
    signals = SignalService(db, analysis, timeline, bus)
    paper = PaperService(db, env, settings, analysis, options, timeline)

    def default_adapter():
        from ..agents.tradingagents_adapter import TradingAgentsAdapter  # heavy import, only when agents run

        agents = settings().agents
        return TradingAgentsAdapter(env, models, agents.max_tool_rounds, agents.max_minutes_per_analyst)

    orchestrator = AgentOrchestrator(db, analysis, adapter_factory or default_adapter, timeline, bus, settings)
    assistant = Assistant(analysis, options, orchestrator, commentary, models, db, registry)
    monitor = MonitorService(analysis, options, commentary, alerts, signals, timeline, bus, settings)
    replay = ReplayService(analysis, commentary, bus, timeline, settings)
    backtests = BacktestService(db, analysis, settings, timeline, bus)
    started_at = now_ist()
    health = HealthService(env, db, provider, models, bus, monitor, settings_store, timeline, started_at, registry)
    return Services(env, db, bus, cache, registry, provider, settings_store, timeline, models, analysis, options, stocks,
                    commentary, alerts, signals, paper, orchestrator, assistant, monitor, replay, backtests, health, RateLimiter(),
                    started_at)
