"""Alert rules evaluated on every market snapshot, with cooldowns and multi-channel delivery.

Browser, sound and voice channels are delivered by the dashboard (the event carries the flags);
Telegram, email and webhook are sent by the backend when configured in the environment.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..config import TIMEFRAMES, EnvConfig
from ..data.models import now_ist
from ..data.symbols import SYMBOL_RE
from ..storage.db import Database, dumps, loads
from .bus import EventBus
from .notifiers import NotificationError, send_email, send_telegram, send_webhook

Channel = Literal["dashboard", "browser", "sound", "voice", "telegram", "email", "webhook"]
RuleType = Literal[
    "price_above", "price_below", "signal_label", "confidence_above", "event", "regime_change",
    "pcr_above", "pcr_below", "support_test", "resistance_test",
]


def _default_channels() -> list[Channel]:
    return ["dashboard", "browser", "sound"]


class AlertRule(BaseModel):
    type: RuleType
    symbol: str = Field(max_length=32)
    timeframe: str | None = None
    value: float | None = None
    label: str | None = Field(None, max_length=60)
    event_kind: str | None = Field(None, max_length=40)

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not SYMBOL_RE.match(value):
            raise ValueError("invalid symbol")
        return value

    @field_validator("timeframe")
    @classmethod
    def _tf(cls, value: str | None) -> str | None:
        if value is not None and value not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {TIMEFRAMES}")
        return value

    @model_validator(mode="after")
    def _needs(self) -> AlertRule:
        if self.type in ("price_above", "price_below", "confidence_above", "pcr_above", "pcr_below") and self.value is None:
            raise ValueError(f"{self.type} requires a value")
        if self.type == "signal_label" and not self.label:
            raise ValueError("signal_label requires a label")
        if self.type == "event" and not self.event_kind:
            raise ValueError("event requires an event_kind")
        return self


class AlertIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    rule: AlertRule
    channels: list[Channel] = Field(default_factory=lambda: _default_channels(), min_length=1)
    cooldown_seconds: int = Field(900, ge=30, le=86400)
    enabled: bool = True


def condition(rule: AlertRule, snap: dict, prev: dict | None) -> str | None:
    """Return the alert message when the rule fires on this snapshot (edge-triggered where it matters)."""
    if rule.timeframe and snap["timeframe"] != rule.timeframe:
        return None
    price = snap.get("price")
    prev_price = prev.get("price") if prev else None
    signal = snap.get("signal") or {}
    if rule.type == "price_above" and price is not None and price > rule.value and (prev_price is None or prev_price <= rule.value):
        return f"{rule.symbol} traded above {rule.value:,.2f} (last {price:,.2f})"
    if rule.type == "price_below" and price is not None and price < rule.value and (prev_price is None or prev_price >= rule.value):
        return f"{rule.symbol} traded below {rule.value:,.2f} (last {price:,.2f})"
    if rule.type == "signal_label":
        prev_label = ((prev or {}).get("signal") or {}).get("label")
        if signal.get("label") == rule.label and prev_label != rule.label:
            return f"{rule.symbol} {snap['timeframe']} signal is now {rule.label} (model confidence {signal.get('model_confidence')}%)"
    if rule.type == "confidence_above":
        prev_conf = ((prev or {}).get("signal") or {}).get("model_confidence")
        conf = signal.get("model_confidence")
        if conf is not None and conf >= rule.value and (prev_conf is None or prev_conf < rule.value):
            return f"{rule.symbol} {snap['timeframe']} model confidence {conf}% ≥ {rule.value:g}% ({signal.get('label')})"
    if rule.type == "event":
        for event in snap.get("new_events") or []:
            if event["kind"] == rule.event_kind:
                return f"{rule.symbol} {snap['timeframe']}: {event['message']}"
    if rule.type in ("support_test", "resistance_test"):
        for event in snap.get("new_events") or []:
            if event["kind"] == rule.type:
                return f"{rule.symbol} {snap['timeframe']}: {event['message']}"
    if rule.type == "regime_change" and prev and (prev.get("regime") or {}).get("code") != (snap.get("regime") or {}).get("code"):
        return f"{rule.symbol} {snap['timeframe']} regime changed: {prev['regime']['label']} → {snap['regime']['label']}"
    options = snap.get("options") or {}
    pcr, prev_pcr = options.get("pcr_oi"), ((prev or {}).get("options") or {}).get("pcr_oi")
    if rule.type == "pcr_above" and pcr is not None and pcr > rule.value and (prev_pcr is None or prev_pcr <= rule.value):
        return f"{rule.symbol} PCR (OI) rose above {rule.value:g} (now {pcr:.2f})"
    if rule.type == "pcr_below" and pcr is not None and pcr < rule.value and (prev_pcr is None or prev_pcr >= rule.value):
        return f"{rule.symbol} PCR (OI) fell below {rule.value:g} (now {pcr:.2f})"
    return None


class AlertService:
    def __init__(self, db: Database, env: EnvConfig, bus: EventBus):
        self.db = db
        self.env = env
        self.bus = bus
        self._prev: dict[tuple[str, str], dict] = {}
        self._lock = threading.Lock()

    # CRUD -------------------------------------------------------------------------
    def all(self) -> list[dict]:
        rows = self.db.query("SELECT * FROM alerts ORDER BY id DESC")
        for row in rows:
            row["rule"], row["channels"], row["enabled"] = loads(row["rule"]), loads(row["channels"]), bool(row["enabled"])
        return rows

    def create(self, alert: AlertIn) -> dict:
        alert_id = self.db.execute(
            "INSERT INTO alerts(name, rule, channels, enabled, cooldown_seconds, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (alert.name, dumps(alert.rule.model_dump()), dumps(alert.channels), int(alert.enabled), alert.cooldown_seconds,
             now_ist().isoformat()),
        )
        return next(a for a in self.all() if a["id"] == alert_id)

    def update(self, alert_id: int, alert: AlertIn) -> dict | None:
        count = self.db.execute(
            "UPDATE alerts SET name=?, rule=?, channels=?, enabled=?, cooldown_seconds=? WHERE id=?",
            (alert.name, dumps(alert.rule.model_dump()), dumps(alert.channels), int(alert.enabled), alert.cooldown_seconds, alert_id),
        )
        return next((a for a in self.all() if a["id"] == alert_id), None) if count else None

    def delete(self, alert_id: int) -> bool:
        return bool(self.db.execute("DELETE FROM alerts WHERE id = ?", (alert_id,)))

    def events(self, limit: int = 200) -> list[dict]:
        rows = self.db.query("SELECT * FROM alert_events ORDER BY id DESC LIMIT ?", (limit,))
        for row in rows:
            row["payload"], row["delivery"] = loads(row["payload"]), loads(row["delivery"])
        return rows

    # evaluation -------------------------------------------------------------------
    def check(self, snap: dict) -> list[dict]:
        key = (snap["symbol"], snap["timeframe"])
        with self._lock:
            prev = self._prev.get(key)
            self._prev[key] = {"price": snap.get("price"), "signal": snap.get("signal"), "regime": snap.get("regime"),
                               "options": snap.get("options")}
        fired = []
        now = now_ist()
        for alert in self.all():
            if not alert["enabled"]:
                continue
            rule = AlertRule.model_validate(alert["rule"])
            if rule.symbol != snap["symbol"]:
                continue
            last = alert["last_triggered_at"]
            if last and (now - datetime.fromisoformat(last)).total_seconds() < alert["cooldown_seconds"]:
                continue
            message = condition(rule, snap, prev)
            if message:
                fired.append(self.deliver(alert, message, snap))
        return fired

    def deliver(self, alert: dict, message: str, snap: dict | None = None) -> dict:
        now = now_ist().isoformat()
        channels = alert["channels"]
        delivery: dict[str, str] = {}
        payload = {"alert_id": alert.get("id"), "name": alert["name"], "message": message, "symbol": (snap or {}).get("symbol"),
                   "ts": now, "priority": "HIGH"}
        for channel in ("dashboard", "browser", "sound", "voice"):
            if channel in channels:
                delivery[channel] = "sent to dashboard"
        threads = []
        for channel, fn in (("telegram", lambda: send_telegram(self.env, f"🔔 {alert['name']}\n{message}")),
                            ("webhook", lambda: send_webhook(self.env, payload)),
                            ("email", lambda: send_email(self.env, f"Alert: {alert['name']}", message))):
            if channel in channels:
                delivery[channel] = "pending"
                threads.append((channel, fn))
        event_id = self.db.execute(
            "INSERT INTO alert_events(alert_id, ts, symbol, message, payload, delivery) VALUES (?, ?, ?, ?, ?, ?)",
            (alert.get("id"), now, payload["symbol"], message, dumps(payload), dumps(delivery)),
        )
        if alert.get("id"):
            self.db.execute("UPDATE alerts SET last_triggered_at = ? WHERE id = ?", (now, alert["id"]))
        self.bus.publish("alert", {**payload, "event_id": event_id, "channels": channels})
        if threads:
            threading.Thread(target=self._send_external, args=(event_id, threads, delivery), daemon=True).start()
        return {**payload, "event_id": event_id, "delivery": delivery}

    def _send_external(self, event_id: int, jobs: list, delivery: dict) -> None:
        for channel, fn in jobs:
            try:
                delivery[channel] = fn()
            except NotificationError as exc:
                delivery[channel] = f"failed: {exc}"
        self.db.execute("UPDATE alert_events SET delivery = ? WHERE id = ?", (dumps(delivery), event_id))
        self.bus.publish("alert_delivery", {"event_id": event_id, "delivery": delivery})

    def test(self, channels: Sequence[str]) -> dict:
        return self.deliver({"id": None, "name": "Test alert", "channels": list(channels)},
                            "Test notification from the AI Trading Command Center.")
