"""Symbol registry: maps dashboard symbols to Yahoo, NSE, TradingView and option-chain identifiers.

Reference lists (NSE equity list, F&O lot sizes, index constituents) are downloaded at most once a day and kept
on disk. When a download fails, a stale-but-real copy is preferred over no data: first the last downloaded file,
then the snapshot bundled in ``reference_seed/`` (NSE often refuses a new cloud server). Each list records where it
came from and how old it is, for System Health.
"""

from __future__ import annotations

import io
import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from tradingagents.dataflows.india.nse_client import _BROWSER_UA, _nse_session

from .models import IST, DataUnavailable, InstrumentMeta

SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9&\-]{0,19}$")
DAY = 24 * 3600
RETRY_SECONDS = 3600  # a list served from a stale or bundled copy is downloaded again after this long
SEED_DIR = Path(__file__).resolve().parent / "reference_seed"
CURRENT_SOURCES = ("download", "cache")


@dataclass(frozen=True)
class IndexInfo:
    key: str
    name: str
    yahoo: str
    nse_name: str | None  # name in NSE allIndices / chart APIs
    tradingview: str
    exchange: str = "NSE"
    options: bool = False


INDEX_TABLE: dict[str, IndexInfo] = {
    info.key: info
    for info in [
        IndexInfo("NIFTY", "NIFTY 50", "^NSEI", "NIFTY 50", "NSE:NIFTY", options=True),
        IndexInfo("BANKNIFTY", "NIFTY BANK", "^NSEBANK", "NIFTY BANK", "NSE:BANKNIFTY", options=True),
        IndexInfo("FINNIFTY", "NIFTY FINANCIAL SERVICES", "NIFTY_FIN_SERVICE.NS", "NIFTY FINANCIAL SERVICES", "NSE:CNXFINANCE", options=True),
        IndexInfo("MIDCPNIFTY", "NIFTY MIDCAP SELECT", "NIFTY_MID_SELECT.NS", "NIFTY MIDCAP SELECT", "NSE:NIFTY_MID_SELECT", options=True),
        IndexInfo("NIFTYNXT50", "NIFTY NEXT 50", "^NSMIDCP", "NIFTY NEXT 50", "NSE:NIFTYJR", options=True),
        IndexInfo("SENSEX", "BSE SENSEX", "^BSESN", None, "BSE:SENSEX", exchange="BSE"),
        IndexInfo("BANKEX", "BSE BANKEX", "BSE-BANK.BO", None, "BSE:BANKEX", exchange="BSE"),
        IndexInfo("INDIAVIX", "INDIA VIX", "^INDIAVIX", "INDIA VIX", "NSE:INDIAVIX"),
        IndexInfo("NIFTYIT", "NIFTY IT", "^CNXIT", "NIFTY IT", "NSE:CNXIT"),
        IndexInfo("NIFTYPHARMA", "NIFTY PHARMA", "^CNXPHARMA", "NIFTY PHARMA", "NSE:CNXPHARMA"),
        IndexInfo("NIFTYAUTO", "NIFTY AUTO", "^CNXAUTO", "NIFTY AUTO", "NSE:CNXAUTO"),
        IndexInfo("NIFTYFMCG", "NIFTY FMCG", "^CNXFMCG", "NIFTY FMCG", "NSE:CNXFMCG"),
        IndexInfo("NIFTYMETAL", "NIFTY METAL", "^CNXMETAL", "NIFTY METAL", "NSE:CNXMETAL"),
        IndexInfo("NIFTYREALTY", "NIFTY REALTY", "^CNXREALTY", "NIFTY REALTY", "NSE:CNXREALTY"),
        IndexInfo("NIFTYENERGY", "NIFTY ENERGY", "^CNXENERGY", "NIFTY ENERGY", "NSE:CNXENERGY"),
        IndexInfo("NIFTYPSUBANK", "NIFTY PSU BANK", "^CNXPSUBANK", "NIFTY PSU BANK", "NSE:CNXPSUBANK"),
        IndexInfo("NIFTYMEDIA", "NIFTY MEDIA", "^CNXMEDIA", "NIFTY MEDIA", "NSE:CNXMEDIA"),
        IndexInfo("NIFTYINFRA", "NIFTY INFRASTRUCTURE", "^CNXINFRA", "NIFTY INFRASTRUCTURE", "NSE:CNXINFRA"),
        IndexInfo("NIFTYPVTBANK", "NIFTY PRIVATE BANK", "NIFTY_PVT_BANK.NS", "NIFTY PRIVATE BANK", "NSE:NIFTYPVTBANK"),
        IndexInfo("NIFTYMIDCAP100", "NIFTY MIDCAP 100", "NIFTY_MIDCAP_100.NS", "NIFTY MIDCAP 100", "NSE:CNXMIDCAP"),
        IndexInfo("NIFTYSMALLCAP100", "NIFTY SMALLCAP 100", "^CNXSC", "NIFTY SMALLCAP 100", "NSE:CNXSMALLCAP"),
        IndexInfo("NIFTYMIDCAP50", "NIFTY MIDCAP 50", "^NSEMDCP50", "NIFTY MIDCAP 50", "NSE:NIFTYMIDCAP50"),
    ]
}

ALIASES = {
    "NIFTY50": "NIFTY", "NIFTY_50": "NIFTY", "^NSEI": "NIFTY",
    "NIFTYBANK": "BANKNIFTY", "^NSEBANK": "BANKNIFTY",
    "NIFTYFIN": "FINNIFTY", "MIDCAPNIFTY": "MIDCPNIFTY", "NIFTYNEXT50": "NIFTYNXT50",
    "INDIA_VIX": "INDIAVIX", "^INDIAVIX": "INDIAVIX", "^BSESN": "SENSEX",
}

CONSTITUENT_FILES = {
    "NIFTY 50": "ind_nifty50list.csv",
    "NIFTY BANK": "ind_niftybanklist.csv",
    "NIFTY NEXT 50": "ind_niftynext50list.csv",
    "NIFTY 100": "ind_nifty100list.csv",
    "NIFTY 500": "ind_nifty500list.csv",
}


def seed_date() -> str:
    """Date the bundled reference snapshot was downloaded (from ``reference_seed/manifest.json``)."""
    try:
        return str(json.loads((SEED_DIR / "manifest.json").read_text(encoding="utf-8"))["downloaded_on"])
    except (OSError, ValueError, KeyError):
        return "unknown date"


def _file_date(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, IST).date().isoformat()


class SymbolRegistry:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._parsed: dict[str, tuple[float, Any]] = {}
        # file name -> {"source": download | cache | stale cache | bundled snapshot, "as_of": YYYY-MM-DD, "detail": str}
        self.reference_status: dict[str, dict[str, str]] = {}

    # ------------------------------------------------------------------ normalisation
    def normalize(self, raw: str) -> str:
        if not isinstance(raw, str):
            raise ValueError("symbol must be a string")
        value = raw.strip().upper()
        for prefix in ("NSE:", "BSE:"):
            if value.startswith(prefix):
                value = value[len(prefix):]
        if value.endswith(".NS"):
            value = value[:-3]
        value = ALIASES.get(value, value)
        if not SYMBOL_RE.match(value):
            raise ValueError(f"invalid symbol {raw!r}")
        return value

    def is_index(self, symbol: str) -> bool:
        return symbol in INDEX_TABLE

    def index_info(self, symbol: str) -> IndexInfo | None:
        return INDEX_TABLE.get(symbol)

    # ------------------------------------------------------------------ reference lists
    def _note(self, name: str, source: str, as_of: str, detail: str = "") -> None:
        self.reference_status[name] = {"source": source, "as_of": as_of, "detail": detail}

    def _cached_text(self, name: str, url: str, max_age: float, via_nse_session: bool) -> str:
        path = self.cache_dir / name
        if path.exists() and time.time() - path.stat().st_mtime < max_age:
            self._note(name, "cache", _file_date(path))
            return path.read_text(encoding="utf-8")
        try:
            if via_nse_session:
                resp = _nse_session().get(url, timeout=20)
            else:
                resp = requests.get(url, headers={"User-Agent": _BROWSER_UA}, timeout=20)
            if resp.status_code != 200 or "html" in resp.headers.get("content-type", "").lower():
                raise RuntimeError(f"HTTP {resp.status_code}")
            path.write_text(resp.text, encoding="utf-8")
            self._note(name, "download", _file_date(path))
            return resp.text
        except Exception as exc:  # noqa: BLE001
            reason = f"download failed: {type(exc).__name__}: {str(exc)[:160]}"
            if path.exists():
                self._note(name, "stale cache", _file_date(path), reason)
                return path.read_text(encoding="utf-8")
            seed = SEED_DIR / name
            if seed.exists():
                self._note(name, "bundled snapshot", seed_date(), reason)
                return seed.read_text(encoding="utf-8")
            raise DataUnavailable(name, f"{type(exc).__name__}: {exc}", url) from exc

    def _reference(self, name: str, url: str, via_nse_session: bool, parse: Callable[[str], Any]) -> Any:
        """A parsed reference list, reloaded daily, or hourly while it comes from a stale or bundled copy.

        Call with ``self._lock`` held.
        """
        loaded = self._parsed.get(name)
        current = self.reference_status.get(name, {}).get("source") in CURRENT_SOURCES
        if loaded is not None and time.time() - loaded[0] < (DAY if current else RETRY_SECONDS):
            return loaded[1]
        try:
            value = parse(self._cached_text(name, url, DAY, via_nse_session))
        except DataUnavailable:
            if loaded is None:
                raise
            value = loaded[1]  # keep serving the copy already in memory
        self._parsed[name] = (time.time(), value)
        return value

    def equities(self) -> dict[str, str]:
        def parse(text: str) -> dict[str, str]:
            frame = pd.read_csv(io.StringIO(text))
            frame.columns = [c.strip() for c in frame.columns]
            return dict(zip(frame["SYMBOL"].str.strip(), frame["NAME OF COMPANY"].str.strip(), strict=False))

        with self._lock:
            return self._reference("EQUITY_L.csv", "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", True, parse)

    def lot_sizes(self) -> dict[str, int]:
        def parse(text: str) -> dict[str, int]:
            frame = pd.read_csv(io.StringIO(text))
            frame.columns = [c.strip() for c in frame.columns]
            lots: dict[str, int] = {}
            month_cols = [c for c in frame.columns if c not in ("UNDERLYING", "SYMBOL")]
            for _, row in frame.iterrows():
                symbol = str(row["SYMBOL"]).strip()
                for col in month_cols:
                    try:
                        lots[symbol] = int(float(str(row[col]).strip()))
                        break
                    except ValueError:
                        continue
            return lots

        with self._lock:
            return self._reference("fo_mktlots.csv", "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv", True, parse)

    def fno_stocks(self) -> list[str]:
        return sorted(s for s in self.lot_sizes() if s not in INDEX_TABLE and SYMBOL_RE.match(s))

    def constituents(self, index_name: str = "NIFTY 50") -> list[dict]:
        if index_name not in CONSTITUENT_FILES:
            raise DataUnavailable(index_name, "no constituent list configured for this index")
        file = CONSTITUENT_FILES[index_name]

        def parse(text: str) -> list[dict]:
            frame = pd.read_csv(io.StringIO(text))
            frame.columns = [c.strip() for c in frame.columns]
            return [
                {"symbol": str(r["Symbol"]).strip(), "name": str(r["Company Name"]).strip(), "industry": str(r["Industry"]).strip()}
                for _, r in frame.iterrows()
            ]

        with self._lock:
            return self._reference(file, f"https://niftyindices.com/IndexConstituent/{file}", False, parse)

    def sector(self, symbol: str) -> str | None:
        for index_name in ("NIFTY 500", "NIFTY 50"):
            try:
                for row in self.constituents(index_name):
                    if row["symbol"] == symbol:
                        return row["industry"]
            except DataUnavailable:
                continue
        return None

    # ------------------------------------------------------------------ metadata
    def validate(self, raw: str) -> str:
        """Normalise and check the symbol exists (indices, or NSE equities when the list is available)."""
        symbol = self.normalize(raw)
        if symbol in INDEX_TABLE:
            return symbol
        try:
            if symbol not in self.equities():
                raise ValueError(f"{symbol} is not an NSE-listed equity or supported index")
        except DataUnavailable:
            pass  # cannot verify offline; downstream providers report missing data
        return symbol

    def meta(self, symbol: str) -> InstrumentMeta:
        info = INDEX_TABLE.get(symbol)
        try:
            lots = self.lot_sizes()
        except DataUnavailable:
            lots = {}
        if info:
            return InstrumentMeta(
                symbol=symbol, name=info.name, kind="index", exchange=info.exchange, yahoo_symbol=info.yahoo,
                tradingview_symbol=info.tradingview, nse_index_name=info.nse_name,
                option_type="Indices" if info.options else None, lot_size=lots.get(symbol), has_volume=False,
            )
        try:
            name = self.equities().get(symbol, symbol)
        except DataUnavailable:
            name = symbol
        return InstrumentMeta(
            symbol=symbol, name=name, kind="stock", exchange="NSE", yahoo_symbol=f"{symbol}.NS",
            tradingview_symbol=f"NSE:{symbol}", option_type="Equity" if symbol in lots else None,
            lot_size=lots.get(symbol), sector=self.sector(symbol), has_volume=True,
        )

    def search(self, query: str, limit: int = 20) -> list[dict]:
        q = query.strip().upper()
        results = [
            {"symbol": key, "name": info.name, "kind": "index"}
            for key, info in INDEX_TABLE.items()
            if q in key or q in info.name
        ]
        try:
            for symbol, name in self.equities().items():
                if len(results) >= limit:
                    break
                if symbol.startswith(q) or q in name.upper():
                    results.append({"symbol": symbol, "name": name, "kind": "stock"})
        except DataUnavailable:
            pass
        return results[:limit]
