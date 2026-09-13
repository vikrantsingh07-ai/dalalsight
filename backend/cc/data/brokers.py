"""Broker data-feed slots (Zerodha Kite Connect, Upstox, Dhan).

Authorised broker feeds are what provide real-time ticks, index-futures volume (needed for
index VWAP/volume analysis) and order execution. No broker adapter is implemented in this
build; selecting one reports exactly which credentials and work are required instead of
returning any data.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date

import pandas as pd

from ..config import EnvConfig, MarketHoursSettings
from .cache import TTLCache
from .composite import CompositePublicProvider
from .models import DataUnavailable, InstrumentMeta, MarketStatus, OptionChain, ProviderHealth, Quote
from .nse import NSEPublicProvider
from .provider import MarketDataProvider
from .symbols import SymbolRegistry
from .yahoo import YahooProvider

BROKERS: dict[str, tuple[str, list[str]]] = {
    "kite": ("Zerodha Kite Connect", ["MARKET_DATA_API_KEY", "MARKET_DATA_API_SECRET", "MARKET_DATA_ACCESS_TOKEN"]),
    "upstox": ("Upstox API v2", ["MARKET_DATA_API_KEY", "MARKET_DATA_ACCESS_TOKEN"]),
    "dhan": ("DhanHQ API", ["MARKET_DATA_API_KEY", "MARKET_DATA_ACCESS_TOKEN"]),
}


class BrokerFeedProvider(MarketDataProvider):
    def __init__(self, key: str, registry: SymbolRegistry):
        super().__init__()
        self.name = key
        self.label, self.required_env = BROKERS[key]
        self.registry = registry

    @property
    def configured(self) -> bool:
        return all(os.environ.get(name) for name in self.required_env)

    def _unavailable(self, what: str) -> DataUnavailable:
        reason = "credentials present but the adapter is not implemented in this build" if self.configured else "credentials not configured"
        return DataUnavailable(what, reason, self.label, ", ".join(self.required_env) + f" and a {self.label} adapter")

    def get_quote(self, symbol: str) -> Quote:
        raise self._unavailable(f"{symbol} quote")

    def get_ohlcv(self, symbol: str, timeframe: str, bars: int = 500) -> pd.DataFrame:
        raise self._unavailable(f"{symbol} {timeframe} OHLCV")

    def get_option_chain(self, symbol: str, expiry: date) -> OptionChain:
        raise self._unavailable(f"{symbol} option chain")

    def get_expiries(self, symbol: str) -> list[date]:
        raise self._unavailable(f"{symbol} expiries")

    def get_instrument_metadata(self, symbol: str) -> InstrumentMeta:
        return self.registry.meta(symbol)

    def get_market_status(self) -> MarketStatus:
        raise self._unavailable("market status")

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.label,
            status="ERROR" if self.configured else "NOT_CONFIGURED",
            detail=self._unavailable("feed").reason + f"; required: {', '.join(self.required_env)}",
        )


def build_provider(env: EnvConfig, registry: SymbolRegistry, cache: TTLCache,
                   hours: Callable[[], MarketHoursSettings]) -> MarketDataProvider:
    key = env.market_data_provider
    if key == "public":
        yahoo = YahooProvider(registry, cache)
        nse = NSEPublicProvider(registry, cache)
        return CompositePublicProvider(yahoo, nse, registry, hours)
    if key in BROKERS:
        return BrokerFeedProvider(key, registry)
    raise ValueError(f"MARKET_DATA_PROVIDER must be one of public, {', '.join(BROKERS)}; got {key!r}")
