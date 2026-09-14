"""Configuration.

* ``EnvConfig`` — process-level values and secrets from environment variables / ``.env``.
  Secrets never leave the backend: ``EnvConfig.public()`` only reports whether they are set.
* ``RuntimeSettings`` — user-editable settings persisted in the database and validated here.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRADINGAGENTS_DIR = PROJECT_ROOT / "packages" / "tradingagents"  # TradingAgents India, vendored in this repo
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

Priority = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
PRIORITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
TIMEFRAMES: tuple[str, ...] = ("1m", "3m", "5m", "15m", "30m", "1h", "4h", "1D", "1W")
TIMEFRAME_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1D": 1440, "1W": 10080}


def load_environment() -> None:
    """Load the repo-root ``.env`` and then ``packages/tradingagents/.env`` if one exists.

    Variables already present in the process environment always win.
    """
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    ta_dir = Path(os.environ.get("TRADINGAGENTS_DIR") or TRADINGAGENTS_DIR)
    load_dotenv(ta_dir / ".env", override=False)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class EnvConfig:
    host: str
    port: int
    db_path: Path
    dev_mode: bool
    access_token: str
    ai_provider: str
    ai_base_url: str
    ai_api_key_env: str
    default_ai_model: str
    fallback_ai_model: str
    ai_timeout_seconds: int
    ai_daily_call_budget: int
    ai_model_cooldown_seconds: int
    market_data_provider: str
    option_data_provider: str
    execution_mode: str
    live_execution_enabled: bool
    tradingview_widget_enabled: bool
    tradingview_library_path: str
    telegram_bot_token: str
    telegram_chat_id: str
    alert_webhook_url: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    alert_email_from: str
    alert_email_to: str
    # Origins allowed to call the API cross-origin, e.g. the dashboard deployed on Vercel.
    cors_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> EnvConfig:
        db_path = Path(_env("CC_DB_PATH", "data/dalalsight.db"))
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path
        execution_mode = _env("EXECUTION_MODE", "analysis").lower()
        if execution_mode not in ("analysis", "paper", "live"):
            raise ValueError(f"EXECUTION_MODE must be analysis, paper or live, got {execution_mode!r}")
        return cls(
            host=_env("CC_HOST", "127.0.0.1"),
            port=_env_int("CC_PORT", _env_int("PORT", 8765)),  # hosting platforms set PORT
            db_path=db_path,
            dev_mode=_env_bool("CC_DEV_MODE", True),
            cors_origins=tuple(origin.strip().rstrip("/") for origin in _env("CC_CORS_ORIGINS").split(",") if origin.strip()),
            access_token=_env("CC_ACCESS_TOKEN"),
            ai_provider=_env("AI_PROVIDER", "openrouter").lower(),
            ai_base_url=_env("AI_BASE_URL", "https://openrouter.ai/api/v1"),
            ai_api_key_env=_env("AI_API_KEY_ENV", "OPENROUTER_API_KEY"),
            default_ai_model=_env("DEFAULT_AI_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free"),
            fallback_ai_model=_env("FALLBACK_AI_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"),
            ai_timeout_seconds=_env_int("AI_TIMEOUT_SECONDS", 120),
            ai_daily_call_budget=_env_int("AI_DAILY_CALL_BUDGET", 45),
            ai_model_cooldown_seconds=_env_int("AI_MODEL_COOLDOWN_SECONDS", 600),
            market_data_provider=_env("MARKET_DATA_PROVIDER", "public").lower(),
            option_data_provider=_env("OPTION_DATA_PROVIDER", "nse").lower(),
            execution_mode=execution_mode,
            live_execution_enabled=_env_bool("LIVE_EXECUTION_ENABLED", False),
            tradingview_widget_enabled=_env_bool("TRADINGVIEW_WIDGET_ENABLED", True),
            tradingview_library_path=_env("TRADINGVIEW_CHARTING_LIBRARY_PATH"),
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
            alert_webhook_url=_env("ALERT_WEBHOOK_URL"),
            smtp_host=_env("SMTP_HOST"),
            smtp_port=_env_int("SMTP_PORT", 587),
            smtp_user=_env("SMTP_USER"),
            smtp_password=_env("SMTP_PASSWORD"),
            alert_email_from=_env("ALERT_EMAIL_FROM"),
            alert_email_to=_env("ALERT_EMAIL_TO"),
        )

    def ai_api_key(self) -> str:
        return _env("AI_API_KEY") or _env(self.ai_api_key_env)

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.alert_email_to)

    def public(self) -> dict:
        """Non-secret view for the UI and health panel."""
        return {
            "host": self.host,
            "port": self.port,
            "dev_mode": self.dev_mode,
            "access_token_required": bool(self.access_token),
            "ai_provider": self.ai_provider,
            "ai_base_url": self.ai_base_url,
            "ai_key_configured": bool(self.ai_api_key()),
            "ai_key_env": "AI_API_KEY" if _env("AI_API_KEY") else self.ai_api_key_env,
            "default_ai_model": self.default_ai_model,
            "fallback_ai_model": self.fallback_ai_model,
            "ai_daily_call_budget": self.ai_daily_call_budget,
            "market_data_provider": self.market_data_provider,
            "option_data_provider": self.option_data_provider,
            "live_execution_enabled": self.live_execution_enabled,
            "tradingview_widget_enabled": self.tradingview_widget_enabled,
            "tradingview_library_configured": bool(self.tradingview_library_path),
            "telegram_configured": self.telegram_configured,
            "webhook_configured": bool(self.alert_webhook_url),
            "email_configured": self.email_configured,
        }


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class CommentarySettings(BaseModel):
    enabled: bool = True
    min_interval_seconds: int = Field(120, ge=10, le=3600)
    event_cooldown_seconds: int = Field(900, ge=30, le=14400)
    confidence_change_points: float = Field(15.0, ge=1, le=100)
    level_test_atr: float = Field(0.15, gt=0, le=2)
    llm_min_priority: Priority = "HIGH"
    speak_min_priority: Priority = "HIGH"
    during_market_hours_only: bool = True


class VoiceSettings(BaseModel):
    enabled: bool = True
    voice_name: str = Field("", max_length=120)
    lang: str = Field("en-IN", max_length=16)
    rate: float = Field(1.0, ge=0.5, le=2.0)
    pitch: float = Field(1.0, ge=0.5, le=2.0)


class MarketHoursSettings(BaseModel):
    timezone: str = "Asia/Kolkata"
    pre_open_start: str = "09:00"
    market_open: str = "09:15"
    closing_period_start: str = "15:00"
    market_close: str = "15:30"
    post_close_end: str = "16:00"
    extra_holidays: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("pre_open_start", "market_open", "closing_period_start", "market_close", "post_close_end")
    @classmethod
    def _hhmm(cls, value: str) -> str:
        if not _TIME_RE.match(value):
            raise ValueError("time must be HH:MM (24h)")
        return value

    @field_validator("extra_holidays")
    @classmethod
    def _dates(cls, values: list[str]) -> list[str]:
        for value in values:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
                raise ValueError(f"holiday {value!r} must be YYYY-MM-DD")
        return values

    @model_validator(mode="after")
    def _ordered(self) -> MarketHoursSettings:
        order = [self.pre_open_start, self.market_open, self.closing_period_start, self.market_close, self.post_close_end]
        if order != sorted(order):
            raise ValueError("market hours must be ordered: pre-open ≤ open ≤ closing period ≤ close ≤ post-close")
        return self


class SignalWeights(BaseModel):
    trend: float = Field(20, ge=0, le=100)
    momentum: float = Field(15, ge=0, le=100)
    volume: float = Field(15, ge=0, le=100)
    ema_structure: float = Field(15, ge=0, le=100)
    vwap: float = Field(10, ge=0, le=100)
    market_structure: float = Field(15, ge=0, le=100)
    volatility: float = Field(5, ge=0, le=100)
    options: float = Field(5, ge=0, le=100)

    @model_validator(mode="after")
    def _positive_total(self) -> SignalWeights:
        if sum(self.model_dump().values()) <= 0:
            raise ValueError("at least one signal weight must be positive")
        return self


class SignalSettings(BaseModel):
    weights: SignalWeights = Field(default_factory=SignalWeights)
    bullish_threshold: float = Field(65, ge=50, le=100)
    bearish_threshold: float = Field(35, ge=0, le=50)
    watch_band: float = Field(8, ge=0, le=25)
    min_confidence: float = Field(55, ge=0, le=100)
    min_coverage: float = Field(0.6, ge=0, le=1)
    min_risk_reward: float = Field(1.5, ge=0.1, le=10)
    ema_fast: int = Field(9, ge=2, le=100)
    ema_slow: int = Field(21, ge=3, le=200)
    crossover_confirm_bars: int = Field(2, ge=1, le=10)
    rsi_period: int = Field(14, ge=2, le=100)
    rsi_overbought: float = Field(70, ge=50, le=100)
    rsi_oversold: float = Field(30, ge=0, le=50)
    volume_spike_mult: float = Field(2.0, ge=1, le=10)
    volume_confirm_mult: float = Field(1.5, ge=1, le=10)
    atr_period: int = Field(14, ge=2, le=100)
    supertrend_period: int = Field(10, ge=2, le=100)
    supertrend_mult: float = Field(3.0, ge=0.5, le=10)
    swing_lookback: int = Field(3, ge=1, le=20)
    breakout_lookback: int = Field(20, ge=5, le=200)

    @model_validator(mode="after")
    def _ema_order(self) -> SignalSettings:
        if self.ema_fast >= self.ema_slow:
            raise ValueError("ema_fast must be smaller than ema_slow")
        return self


class RiskSettings(BaseModel):
    profile: Literal["conservative", "moderate", "aggressive"] = "moderate"
    capital: float = Field(500000.0, gt=0, le=1e12)
    risk_per_trade_pct: float = Field(1.0, gt=0, le=10)
    max_stop_atr: float = Field(3.0, gt=0, le=20)


class OptionSettings(BaseModel):
    risk_free_rate: float = Field(0.065, ge=0, le=0.25)
    strikes_around_atm: int = Field(15, ge=3, le=60)
    max_spread_pct: float = Field(5.0, gt=0, le=100)
    min_oi: float = Field(500, ge=0)
    min_volume: float = Field(100, ge=0)
    delta_min: float = Field(0.30, gt=0, lt=1)
    delta_max: float = Field(0.65, gt=0, lt=1)
    hedge_min_days_to_expiry: int = Field(20, ge=0, le=120)

    @model_validator(mode="after")
    def _delta_order(self) -> OptionSettings:
        if self.delta_min >= self.delta_max:
            raise ValueError("delta_min must be smaller than delta_max")
        return self


class MonitorSettings(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"], max_length=20)
    timeframe: str = "5m"
    poll_seconds_open: int = Field(30, ge=5, le=600)
    poll_seconds_closed: int = Field(600, ge=30, le=7200)
    option_symbols: list[str] = Field(default_factory=lambda: ["NIFTY"], max_length=10)
    option_poll_seconds: int = Field(90, ge=30, le=1800)
    oi_change_event_pct: float = Field(10.0, gt=0, le=500)

    @field_validator("timeframe")
    @classmethod
    def _tf(cls, value: str) -> str:
        if value not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {TIMEFRAMES}")
        return value


class NotificationSettings(BaseModel):
    browser: bool = True
    sound: bool = True
    voice: bool = True
    telegram: bool = False
    webhook: bool = False
    email: bool = False


class AgentSettings(BaseModel):
    agent_weights: dict[str, float] = Field(
        default_factory=lambda: {"market": 1.0, "social": 1.0, "news": 1.0, "fundamentals": 1.0, "derivatives": 1.0}
    )
    max_tool_rounds: int = Field(12, ge=1, le=20)
    max_minutes_per_analyst: int = Field(15, ge=2, le=120)

    @field_validator("agent_weights")
    @classmethod
    def _weights(cls, values: dict[str, float]) -> dict[str, float]:
        for key, weight in values.items():
            if weight < 0 or weight > 10:
                raise ValueError(f"agent weight for {key} must be between 0 and 10")
        return values


class RuntimeSettings(BaseModel):
    default_symbol: str = Field("NIFTY", max_length=32)
    default_timeframe: str = "5m"
    theme: Literal["dark", "light"] = "dark"
    ai_model_override: str = Field("", max_length=160)
    execution_mode: Literal["analysis", "paper", "live"] = "analysis"
    watchlist: list[str] = Field(
        default_factory=lambda: ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "INDIAVIX", "RELIANCE", "HDFCBANK", "INFY", "TCS", "ICICIBANK"],
        max_length=100,
    )
    commentary: CommentarySettings = Field(default_factory=CommentarySettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    market_hours: MarketHoursSettings = Field(default_factory=MarketHoursSettings)
    signal: SignalSettings = Field(default_factory=SignalSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    options: OptionSettings = Field(default_factory=OptionSettings)
    monitor: MonitorSettings = Field(default_factory=MonitorSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    agents: AgentSettings = Field(default_factory=AgentSettings)

    @field_validator("default_timeframe")
    @classmethod
    def _tf(cls, value: str) -> str:
        if value not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {TIMEFRAMES}")
        return value


def deep_merge(base: dict, patch: dict) -> dict:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
