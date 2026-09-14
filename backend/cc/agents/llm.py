"""Model manager: configured default model with fallback, cooldowns and a daily call budget.

* model IDs come only from configuration (``DEFAULT_AI_MODEL`` / ``FALLBACK_AI_MODEL`` or the
  settings override); a model that the provider does not list, or that is overloaded, is skipped
* every attempted call counts against ``AI_DAILY_CALL_BUDGET`` (free tiers are rate limited)
* the API key is read from the environment on the backend and never returned by any endpoint
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import requests

from ..config import EnvConfig
from ..data.models import now_ist
from ..storage.db import Database

TRANSIENT = re.compile(r"overloaded|temporarily unavailable|provider_unavailable|rate.?limit|timeout|timed out", re.IGNORECASE)


class AIUnavailable(Exception):
    """No model call is possible right now (key missing, budget exhausted, all models failing)."""


@dataclass
class LLMReply:
    text: str
    model: str
    latency_ms: float


class ModelManager:
    def __init__(self, env: EnvConfig, db: Database, override: Callable[[], str] = lambda: ""):
        self.env = env
        self.db = db
        self._override = override
        self._lock = threading.Lock()
        self._cooldown_until: dict[str, float] = {}
        self._cooldown_reason: dict[str, str] = {}
        self._models: set[str] | None = None
        self._models_checked = 0.0
        self._models_error: str | None = None
        self.last_model: str | None = None
        self.last_error: str | None = None
        self.last_success_at: datetime | None = None

    # ------------------------------------------------------------------ configuration
    def configured_models(self) -> list[str]:
        ordered = [self._override().strip() or self.env.default_ai_model, self.env.default_ai_model, self.env.fallback_ai_model]
        return list(dict.fromkeys(m for m in ordered if m))

    def listed_models(self) -> set[str] | None:
        if time.time() - self._models_checked < 3600:
            return self._models
        try:
            resp = requests.get(f"{self.env.ai_base_url.rstrip('/')}/models", timeout=15)
            resp.raise_for_status()
            self._models = {item["id"] for item in resp.json().get("data", []) if isinstance(item, dict) and "id" in item}
            self._models_error = None
        except Exception as exc:  # noqa: BLE001 — listing is advisory; calls still report real failures
            self._models, self._models_error = None, f"{type(exc).__name__}: {str(exc)[:120]}"
        self._models_checked = time.time()
        return self._models

    def _model_state(self, model: str, listed: set[str] | None) -> tuple[bool, str]:
        if listed is not None and model not in listed:
            return False, "not listed by provider"
        until = self._cooldown_until.get(model, 0)
        if until > time.time():
            return False, f"cooling down {int(until - time.time())}s ({self._cooldown_reason.get(model, 'recent failure')})"
        return True, "available" if listed is not None else "availability not verified (model list unreachable)"

    def active_model(self) -> str | None:
        listed = self.listed_models()
        for model in self.configured_models():
            if self._model_state(model, listed)[0]:
                return model
        return None

    # ------------------------------------------------------------------ budget
    def _today(self) -> str:
        return now_ist().date().isoformat()

    def calls_today(self) -> int:
        row = self.db.query_one("SELECT calls FROM llm_usage WHERE day = ?", (self._today(),))
        return int(row["calls"]) if row else 0

    def budget_left(self) -> int:
        return max(0, self.env.ai_daily_call_budget - self.calls_today())

    def record_call(self, ok: bool) -> None:
        self.db.execute(
            "INSERT INTO llm_usage(day, calls, errors) VALUES (?, 1, ?) "
            "ON CONFLICT(day) DO UPDATE SET calls = calls + 1, errors = errors + excluded.errors",
            (self._today(), 0 if ok else 1),
        )

    def cooldown(self, model: str, reason: str) -> None:
        with self._lock:
            self._cooldown_until[model] = time.time() + self.env.ai_model_cooldown_seconds
            self._cooldown_reason[model] = reason[:120]

    def ensure_ready(self, calls_needed: int = 1) -> None:
        if not self.env.ai_api_key():
            raise AIUnavailable(f"AI API key not configured (set {self.env.ai_api_key_env} or AI_API_KEY in .env)")
        if self.budget_left() < calls_needed:
            raise AIUnavailable(f"daily AI call budget exhausted ({self.calls_today()}/{self.env.ai_daily_call_budget}); resets at midnight IST")

    # ------------------------------------------------------------------ calls
    def chat(self, messages: list[dict], *, max_tokens: int = 1200, temperature: float = 0.2, purpose: str = "") -> LLMReply:
        self.ensure_ready()
        listed = self.listed_models()
        errors = []
        for model in self.configured_models():
            usable, why = self._model_state(model, listed)
            if not usable:
                errors.append(f"{model}: {why}")
                continue
            if self.budget_left() < 1:
                break
            started = time.perf_counter()
            try:
                text = self._post(model, messages, max_tokens, temperature, purpose)
            except _ModelFailure as exc:
                self.record_call(False)
                self.last_error = f"{model}: {exc}"
                errors.append(self.last_error)
                if exc.fatal:
                    raise AIUnavailable(str(exc)) from exc
                self.cooldown(model, str(exc))
                continue
            self.record_call(True)
            self.last_model, self.last_success_at = model, now_ist()
            return LLMReply(text=text, model=model, latency_ms=round((time.perf_counter() - started) * 1000, 1))
        raise AIUnavailable("; ".join(errors) or "no configured model available")

    def _post(self, model: str, messages: list[dict], max_tokens: int, temperature: float, purpose: str) -> str:
        headers = {"Authorization": f"Bearer {self.env.ai_api_key()}", "Content-Type": "application/json",
                   "X-Title": "DalalSight"}
        body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        try:
            resp = requests.post(f"{self.env.ai_base_url.rstrip('/')}/chat/completions", json=body, headers=headers,
                                 timeout=self.env.ai_timeout_seconds)
        except requests.RequestException as exc:
            raise _ModelFailure(f"{type(exc).__name__}: {str(exc)[:160]}") from exc
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        error = payload.get("error") if isinstance(payload, dict) else None
        if resp.status_code == 401 or (isinstance(error, dict) and error.get("code") == 401):
            raise _ModelFailure("provider rejected the API key (401)", fatal=True)
        if resp.status_code >= 400 or error:
            message = (error or {}).get("message") if isinstance(error, dict) else resp.text[:160]
            raise _ModelFailure(f"HTTP {resp.status_code}: {str(message)[:160]}")
        try:
            text = payload["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise _ModelFailure("malformed response") from exc
        if not text.strip():
            raise _ModelFailure("empty completion (output budget consumed by reasoning or provider error)")
        return text.strip()

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        listed = self.listed_models()
        models = []
        for model in self.configured_models():
            usable, why = self._model_state(model, listed)
            role = "override" if model == self._override().strip() and model != self.env.default_ai_model else (
                "default" if model == self.env.default_ai_model else "fallback")
            models.append({"model": model, "role": role, "usable": usable, "state": why})
        active = self.active_model()
        key_ok = bool(self.env.ai_api_key())
        if not key_ok:
            overall = "NOT_CONFIGURED"
        elif active is None:
            overall = "OFFLINE"
        elif active != self.configured_models()[0] or self.budget_left() == 0:
            overall = "DEGRADED"
        else:
            overall = "ONLINE"
        return {
            "status": overall,
            "provider": self.env.ai_provider,
            "base_url": self.env.ai_base_url,
            "key_configured": key_ok,
            "active_model": active,
            "last_model_used": self.last_model,
            "models": models,
            "model_list_error": self._models_error,
            "calls_today": self.calls_today(),
            "daily_budget": self.env.ai_daily_call_budget,
            "budget_left": self.budget_left(),
            "last_error": self.last_error,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
        }


class _ModelFailure(Exception):
    def __init__(self, message: str, fatal: bool = False):
        super().__init__(message)
        self.fatal = fatal


NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> list[float]:
    values = []
    for match in NUMBER_RE.findall(text):
        try:
            values.append(abs(float(match.replace(",", ""))))
        except ValueError:
            continue
    return values


def unverified_numbers(text: str, facts: object, small_ok: float = 12.0) -> list[float]:
    """Numbers in ``text`` that do not appear (within rounding) anywhere in ``facts``.

    Small integers (periods, counts, list numbering) are tolerated; prices and percentages must match.
    """
    known = set(numbers_in(str(facts)))
    unknown = []
    for value in numbers_in(text):
        if value <= small_ok and float(value).is_integer():
            continue
        if not any(abs(value - k) <= max(0.051, abs(k) * 0.0006) for k in known):
            unknown.append(value)
    return unknown
