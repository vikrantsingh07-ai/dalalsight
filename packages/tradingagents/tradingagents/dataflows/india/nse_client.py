"""HTTP access to NSE and BSE public data, with cookie bootstrap and a disk cache.

Two kinds of endpoint are used:

* ``www.nseindia.com/api/...`` JSON endpoints sit behind a bot filter that only
  answers sessions carrying the cookies set by a normal page visit, so a shared
  session is bootstrapped from the home page and rebuilt on failure.
* Daily archive files (F&O bhavcopy, participant OI, security-wise delivery,
  index closes) never change once published. They are cached on disk under
  ``<data_cache_dir>/india/`` so a backtest over many sessions downloads each file
  once. A 404 means "no file for that date" (weekend, holiday, not yet published)
  and returns ``None``; the miss is cached only for dates old enough that the
  file can no longer appear.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterator
from datetime import date, timedelta

import requests

from ..config import get_config
from ..errors import VendorRateLimitError

logger = logging.getLogger(__name__)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
_NSE_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
_SESSION_TTL_SECONDS = 300
_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024


class ExchangeDataUnavailableError(RuntimeError):
    """An exchange endpoint could not be reached or kept failing."""


_session_lock = threading.Lock()
_session: requests.Session | None = None
_session_created = 0.0


def _nse_session(refresh: bool = False) -> requests.Session:
    global _session, _session_created
    with _session_lock:
        expired = time.monotonic() - _session_created > _SESSION_TTL_SECONDS
        if refresh or _session is None or expired:
            session = requests.Session()
            session.headers.update(_NSE_HEADERS)
            try:
                session.get("https://www.nseindia.com/", timeout=15)
            except requests.RequestException as exc:
                logger.warning("NSE cookie bootstrap failed: %s", exc)
            _session, _session_created = session, time.monotonic()
        return _session


def nse_api_json(path: str, params: dict | None = None, *, timeout: float = 20.0, attempts: int = 3):
    """GET ``https://www.nseindia.com/api/<path>`` and return the decoded JSON."""
    url = f"https://www.nseindia.com/api/{path}"
    last_error: Exception | None = None
    for attempt in range(attempts):
        session = _nse_session(refresh=attempt > 0)
        try:
            resp = session.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
        else:
            if resp.status_code == 429:
                raise VendorRateLimitError(f"NSE rate-limited the '{path}' endpoint")
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    last_error = exc
            else:
                last_error = RuntimeError(f"HTTP {resp.status_code}")
        if attempt < attempts - 1:
            time.sleep(1.5 * (attempt + 1))
    raise ExchangeDataUnavailableError(f"NSE API '{path}' unavailable: {last_error}")


def _cache_path(group: str, name: str) -> str:
    directory = os.path.join(get_config()["data_cache_dir"], "india", group)
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, name)


def invalidate_archive(group: str, name: str) -> None:
    """Drop a cached archive that turned out to be unreadable."""
    path = _cache_path(group, name)
    if os.path.exists(path):
        os.remove(path)


def fetch_archive(
    url: str,
    *,
    group: str,
    name: str,
    trade_day: date,
    source: str = "nse",
    timeout: float = 30.0,
    attempts: int = 3,
) -> bytes | None:
    """Return the bytes of a daily exchange archive file, or None if none exists for that day."""
    path = _cache_path(group, name)
    if os.path.exists(path):
        with open(path, "rb") as fh:
            return fh.read()

    # Today's and yesterday's files may still be published; older misses are final.
    miss_is_final = trade_day < date.today() - timedelta(days=1)
    miss_marker = path + ".missing"
    if miss_is_final and os.path.exists(miss_marker):
        return None

    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            if source == "nse":
                resp = _nse_session(refresh=attempt > 0).get(url, timeout=timeout)
            else:
                resp = requests.get(
                    url,
                    headers={"User-Agent": _BROWSER_UA, "Referer": "https://www.bseindia.com/"},
                    timeout=timeout,
                )
        except requests.RequestException as exc:
            last_error = exc
        else:
            is_html = "text/html" in resp.headers.get("content-type", "").lower()
            if resp.status_code == 404 or (resp.status_code == 200 and is_html):
                # Exchanges answer a missing archive with an HTML "not found" page.
                if miss_is_final:
                    with open(miss_marker, "w", encoding="utf-8"):
                        pass
                return None
            if resp.status_code == 200 and resp.content:
                if len(resp.content) > _MAX_ARCHIVE_BYTES:
                    raise ExchangeDataUnavailableError(f"archive {url} is unexpectedly large")
                tmp = path + ".tmp"
                with open(tmp, "wb") as fh:
                    fh.write(resp.content)
                os.replace(tmp, path)
                return resp.content
            if resp.status_code == 429:
                raise VendorRateLimitError(f"exchange rate-limited archive {url}")
            last_error = RuntimeError(f"HTTP {resp.status_code}")
        if attempt < attempts - 1:
            time.sleep(1.5 * (attempt + 1))
    raise ExchangeDataUnavailableError(f"archive {url} unavailable: {last_error}")


def weekdays_back(start: date, max_days: int) -> Iterator[date]:
    """Weekdays from ``start`` backwards, scanning at most ``max_days`` calendar days."""
    day = start
    for _ in range(max_days):
        if day.weekday() < 5:
            yield day
        day -= timedelta(days=1)
