"""Indian market session calendar (configurable hours + NSE holiday list)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..config import MarketHoursSettings
from .models import MarketStatus

SESSION_LABELS = {
    "PRE_OPEN": "Pre-market",
    "OPEN": "Market open",
    "CLOSING": "Closing period",
    "POST_CLOSE": "Post-close",
    "CLOSED": "Market closed",
}


def _t(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def is_trading_day(day: date, holidays: set[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def next_open(now: datetime, hours: MarketHoursSettings, holidays: set[date]) -> datetime:
    tz = ZoneInfo(hours.timezone)
    local = now.astimezone(tz)
    open_t = _t(hours.market_open)
    day = local.date()
    if is_trading_day(day, holidays) and local.time() < open_t:
        return datetime.combine(day, open_t, tz)
    for _ in range(30):
        day += timedelta(days=1)
        if is_trading_day(day, holidays):
            return datetime.combine(day, open_t, tz)
    return datetime.combine(day, open_t, tz)


def market_status(
    now: datetime,
    hours: MarketHoursSettings,
    holidays: set[date],
    exchange_message: str | None = None,
) -> MarketStatus:
    tz = ZoneInfo(hours.timezone)
    local = now.astimezone(tz)
    today = local.date()
    all_holidays = holidays | {date.fromisoformat(d) for d in hours.extra_holidays}

    if today.weekday() >= 5:
        session, reason = "CLOSED", "weekend"
    elif today in all_holidays:
        session, reason = "CLOSED", "exchange holiday"
    else:
        current = local.time()
        if _t(hours.pre_open_start) <= current < _t(hours.market_open):
            session, reason = "PRE_OPEN", "pre-open order collection"
        elif _t(hours.market_open) <= current < _t(hours.closing_period_start):
            session, reason = "OPEN", "normal trading session"
        elif _t(hours.closing_period_start) <= current < _t(hours.market_close):
            session, reason = "CLOSING", "last part of the session"
        elif _t(hours.market_close) <= current < _t(hours.post_close_end):
            session, reason = "POST_CLOSE", "closing session / post-close"
        else:
            session, reason = "CLOSED", "outside market hours"

    return MarketStatus(
        session=session,
        is_trading=session in ("OPEN", "CLOSING"),
        label=SESSION_LABELS[session],
        now=local,
        session_date=last_session_date(local, hours, all_holidays),
        next_open=None if session in ("OPEN", "CLOSING") else next_open(local, hours, all_holidays),
        reason=reason,
        exchange_message=exchange_message,
    )


def last_session_date(now: datetime, hours: MarketHoursSettings, holidays: set[date]) -> date:
    """The most recent trading day whose session has started (today once pre-open begins)."""
    tz = ZoneInfo(hours.timezone)
    local = now.astimezone(tz)
    day = local.date()
    if is_trading_day(day, holidays) and local.time() >= _t(hours.market_open):
        return day
    for _ in range(30):
        day -= timedelta(days=1)
        if is_trading_day(day, holidays):
            return day
    return day
