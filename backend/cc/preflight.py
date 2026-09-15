"""Deployment preflight: ``python -m cc --check``.

Checks this machine's configuration and whether it can really reach the market-data and AI providers, before you
rely on it. NSE's public site often refuses cloud and overseas IP addresses, so run this first on a new server.
It makes no AI model calls (the daily budget is untouched) and only writes the reference-list cache.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .config import LOOPBACK_HOSTS, PROJECT_ROOT, EnvConfig, MarketHoursSettings

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass
class Check:
    status: str
    name: str
    detail: str


def server_mode(env: EnvConfig) -> bool:
    """Reachable by others: bound beyond localhost, serving another origin, or dev mode switched off (behind a proxy)."""
    return env.host not in LOOPBACK_HOSTS or bool(env.cors_origins) or not env.dev_mode


def config_checks(env: EnvConfig) -> list[Check]:
    checks: list[Check] = []
    server = server_mode(env)
    if env.access_token:
        short = len(env.access_token) < 24
        checks.append(Check(WARN if short else PASS, "Access token", "set, but shorter than 24 characters" if short else "set"))
    elif server:
        checks.append(Check(FAIL, "Access token", "CC_ACCESS_TOKEN is empty: anyone who reaches this server could use the API"))
    else:
        checks.append(Check(PASS, "Access token", "not set (fine while only this computer can reach the server)"))
    if server:
        checks.append(Check(WARN if env.dev_mode else PASS, "Dev mode",
                            "CC_DEV_MODE=true also allows the Vite dev-server origins; set it to false" if env.dev_mode else "off"))
    checks.append(Check(PASS, "CORS origins", ", ".join(env.cors_origins) or "none (only the dashboard this server serves can call it)"))
    checks.append(Check(PASS if env.ai_api_key() else WARN, "AI API key",
                        "set" if env.ai_api_key() else f"{env.ai_api_key_env} is empty: agent runs are refused and commentary uses engine text"))
    checks.append(Check(WARN if env.live_execution_enabled else PASS, "Live execution",
                        "LIVE_EXECUTION_ENABLED=true (orders are still refused: no broker adapter); set it to false"
                        if env.live_execution_enabled else "disabled"))
    if str(env.db_path) != ":memory:":
        folder = env.db_path.parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / ".preflight-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            checks.append(Check(PASS, "Data folder", f"{folder} is writable"))
        except OSError as exc:
            checks.append(Check(FAIL, "Data folder", f"{folder}: {exc}"))
    built = (PROJECT_ROOT / "web" / "dist" / "index.html").is_file()
    checks.append(Check(PASS if built else WARN, "Built dashboard",
                        "web/dist is present" if built else "web/dist is missing: fine when the dashboard is on Vercel, otherwise build web/"))
    return checks


def network_checks(env: EnvConfig) -> list[Check]:
    from .agents.llm import ModelManager
    from .data.brokers import build_provider
    from .data.cache import TTLCache
    from .data.composite import CompositePublicProvider
    from .data.symbols import CURRENT_SOURCES, SymbolRegistry
    from .storage.db import Database

    checks: list[Check] = []

    def probe(name: str, fn: Callable[[], str]) -> None:
        started = time.perf_counter()
        try:
            detail = fn()
        except Exception as exc:  # noqa: BLE001 — every failure is a finding, never a crash
            reason = getattr(exc, "reason", None) or f"{type(exc).__name__}: {exc}"
            checks.append(Check(FAIL, name, str(reason)[:220]))
            return
        checks.append(Check(PASS, name, f"{detail} ({time.perf_counter() - started:.1f}s)"))

    registry = SymbolRegistry(PROJECT_ROOT / "data" / "reference")
    provider = build_provider(env, registry, TTLCache(), MarketHoursSettings)
    if isinstance(provider, CompositePublicProvider):
        nse, yahoo = provider.nse, provider.yahoo

        def nse_quote() -> str:
            quote = nse.get_quote("NIFTY")
            return f"NIFTY {quote.price:,.2f} at {quote.timestamp:%d %b %H:%M} IST"

        def nse_chain() -> str:
            expiry = nse.get_expiries("NIFTY")[0]
            return f"{len(nse.get_option_chain('NIFTY', expiry).rows)} NIFTY strikes for {expiry:%d %b %Y}"

        def yahoo_stock() -> str:
            quote = yahoo.get_quote("RELIANCE")
            return f"RELIANCE {quote.price:,.2f} at {quote.timestamp:%d %b %H:%M}"

        def yahoo_bars() -> str:
            frame = yahoo.get_ohlcv("NIFTY", "15m", 300)
            return f"{len(frame)} NIFTY 15m bars, last {frame.index[-1]:%d %b %H:%M}"

        probe("NSE index quotes", nse_quote)
        probe("NSE option chain", nse_chain)
        probe("Yahoo stock quotes", yahoo_stock)
        probe("Yahoo intraday bars", yahoo_bars)
        status = provider.get_market_status()
        holidays_ok = "holiday list unavailable" not in status.reason
        checks.append(Check(PASS if holidays_ok else WARN, "Market calendar", f"{status.label}: {status.reason}"))
    else:
        checks.append(Check(FAIL, "Market data provider", provider.health().detail))

    def reference() -> str:
        registry.lot_sizes()
        registry.equities()
        return f"{len(registry.lot_sizes())} F&O lot sizes, {len(registry.equities())} NSE equities"

    probe("Reference lists", reference)
    behind = {name: s for name, s in registry.reference_status.items() if s["source"] not in CURRENT_SOURCES}
    if behind:
        checks.append(Check(WARN, "Reference freshness", "; ".join(f"{name}: {s['source']} from {s['as_of']}" for name, s in behind.items())))

    models = ModelManager(env, Database(":memory:"))
    listed = models.listed_models()
    if listed is None:
        checks.append(Check(WARN, "AI model list", f"could not read {env.ai_base_url}/models: {models._models_error}"))
    else:
        missing = [m for m in models.configured_models() if m not in listed]
        checks.append(Check(FAIL if len(missing) == len(models.configured_models()) else WARN if missing else PASS, "AI models",
                            f"not offered by the provider: {', '.join(missing)}" if missing else ", ".join(models.configured_models())))
    return checks


def supabase_checks(env: EnvConfig, network: bool) -> list[Check]:
    """The cloud copy of all data and logs (services/supabase_sync.py)."""
    if not env.supabase_url and not env.supabase_secret_key:
        return [Check(WARN, "Supabase sync", "off: set SUPABASE_URL and SUPABASE_SECRET_KEY to copy data and logs to Supabase")]
    missing = [name for name, value in (("SUPABASE_URL", env.supabase_url), ("SUPABASE_SECRET_KEY", env.supabase_secret_key)) if not value]
    if missing:
        return [Check(FAIL, "Supabase sync", f"{' and '.join(missing)} is empty")]
    if not network:
        return [Check(PASS, "Supabase sync", "configured")]
    import requests

    from .services.supabase_sync import supabase_headers

    try:
        response = requests.get(f"{env.supabase_url.rstrip('/')}/rest/v1/settings", params={"select": "key", "limit": "1"},
                                headers=supabase_headers(env.supabase_secret_key), timeout=15)
    except requests.RequestException as exc:
        return [Check(FAIL, "Supabase sync", f"cannot reach {env.supabase_url}: {type(exc).__name__}")]
    if response.status_code == 200:
        return [Check(PASS, "Supabase sync", f"{env.supabase_url} reachable, tables present")]
    if response.status_code in (401, 403):
        return [Check(FAIL, "Supabase sync", "the key was refused: use the project's secret key (sb_secret_…), not the publishable one")]
    return [Check(FAIL, "Supabase sync", f"HTTP {response.status_code}: {response.text[:160]}")]


def run(env: EnvConfig, network: bool = True) -> int:
    checks = config_checks(env) + supabase_checks(env, network) + (network_checks(env) if network else [])
    width = max(len(check.name) for check in checks)
    print(f"DalalSight preflight - {env.host}:{env.port}" + (" (server mode)" if server_mode(env) else " (local mode)"))
    for check in checks:
        print(f"  {check.status}  {check.name:<{width}}  {check.detail}")
    failed = sum(check.status == FAIL for check in checks)
    warnings = sum(check.status == WARN for check in checks)
    print(f"{len(checks)} checks: {failed} failed, {warnings} warning(s)")
    return 1 if failed else 0
