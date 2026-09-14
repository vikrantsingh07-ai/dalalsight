"""System health: every component reports ONLINE / DEGRADED / OFFLINE / ERROR (or NOT_CONFIGURED / DISABLED)."""

from __future__ import annotations

import importlib.metadata
import os
from datetime import datetime, timedelta

from .. import __version__
from ..config import EnvConfig
from ..data.brokers import BROKERS
from ..data.models import now_ist

CORE = {"Database", "Market data provider", "Market monitor"}


class HealthService:
    def __init__(self, env: EnvConfig, db, provider, models, bus, monitor, settings_store, timeline, started_at: datetime):
        self.env = env
        self.db = db
        self.provider = provider
        self.models = models
        self.bus = bus
        self.monitor = monitor
        self.settings_store = settings_store
        self.timeline = timeline
        self.started_at = started_at

    def report(self) -> dict:
        components: list[dict] = []

        def add(name: str, status: str, detail: str = "", **extra) -> None:
            components.append({"name": name, "status": status, "detail": detail, **extra})

        uptime = now_ist() - self.started_at
        add("API server", "ONLINE", f"v{__version__}, uptime {str(uptime).split('.')[0]}", host=f"{self.env.host}:{self.env.port}")
        add("Database", "ONLINE" if self.db.ping() else "ERROR", str(self.db.path))

        ph = self.provider.health()
        add("Market data provider", ph.status, ph.detail, provider=ph.name, capabilities=ph.capabilities)
        for child in getattr(self.provider, "child_health", lambda: [])():
            add(f"Feed · {child.name}", child.status, child.last_error if child.status != "ONLINE" and child.last_error else child.detail,
                last_success=child.last_success.isoformat() if child.last_success else None, latency_ms=child.latency_ms)

        ai = self.models.status()
        add("AI model", ai["status"], f"active: {ai['active_model'] or 'none'} · calls today {ai['calls_today']}/{ai['daily_budget']}",
            active_model=ai["active_model"], models=ai["models"], last_error=ai["last_error"])
        try:
            version = importlib.metadata.version("tradingagents")
            add("TradingAgents (5 analysts)", "ONLINE", f"tradingagents {version} (editable install)")
        except importlib.metadata.PackageNotFoundError:
            add("TradingAgents (5 analysts)", "ERROR", "package not installed in this environment")

        mon = self.monitor.status()
        if not mon["running"]:
            status = "OFFLINE"
        elif mon["last_cycle_at"] and now_ist() - datetime.fromisoformat(mon["last_cycle_at"]) > timedelta(seconds=3 * (mon["interval"] or 60) + 30):
            status = "DEGRADED"
        else:
            status = "DEGRADED" if mon["symbol_errors"] else "ONLINE"
        add("Market monitor", status, f"cycles {mon['cycles']}, last {mon['last_cycle_at'] or 'never'}, took {mon['cycle_seconds']}s"
            + (f"; unavailable: {', '.join(mon['symbol_errors'])}" if mon["symbol_errors"] else ""))
        add("WebSocket push", "ONLINE", f"{self.bus.client_count} dashboard client(s)")

        for key, (label, required) in BROKERS.items():
            configured = all(os.environ.get(name) for name in required)
            add(f"Broker feed · {label}", "ERROR" if configured and self.env.market_data_provider == key else "NOT_CONFIGURED",
                "adapter not implemented" if configured else f"requires {', '.join(required)}")

        add("Telegram alerts", "ONLINE" if self.env.telegram_configured else "NOT_CONFIGURED", "TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID")
        add("Email alerts", "ONLINE" if self.env.email_configured else "NOT_CONFIGURED", "SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO")
        add("Webhook alerts", "ONLINE" if self.env.alert_webhook_url else "NOT_CONFIGURED", "ALERT_WEBHOOK_URL")
        add("TradingView", "ONLINE" if self.env.tradingview_widget_enabled else "DISABLED",
            "charts open in TradingView itself (embedded TradingView charts cannot show NSE/BSE data); "
            "on-chart signals come from the Command Center Pine Script indicator")
        settings = self.settings_store.get()
        add("Execution safety", "ONLINE", f"mode {settings.execution_mode.upper()}; live execution "
            + ("ENABLED in env but no broker adapter" if self.env.live_execution_enabled else "disabled"))
        if self.settings_store.load_error:
            add("Settings", "DEGRADED", self.settings_store.load_error)

        since = (now_ist() - timedelta(hours=1)).isoformat()
        errors = self.db.query_one("SELECT COUNT(*) AS n FROM errors WHERE ts >= ?", (since,))["n"]
        add("Errors (last hour)", "ONLINE" if errors == 0 else "DEGRADED", f"{errors} logged")

        core = [c for c in components if c["name"] in CORE]
        if any(c["status"] == "ERROR" for c in core):
            overall = "ERROR"
        elif any(c["status"] in ("DEGRADED", "OFFLINE") for c in core) or any(c["name"] == "AI model" and c["status"] != "ONLINE" for c in components):
            overall = "DEGRADED"
        else:
            overall = "ONLINE"
        return {"overall": overall, "generated_at": now_ist().isoformat(), "components": components,
                "recent_errors": self.timeline.errors(10)}
