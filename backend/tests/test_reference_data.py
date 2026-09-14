import os
import time

import pytest
import requests

from cc.data import symbols
from cc.data.models import DataUnavailable
from cc.data.symbols import SEED_DIR, SymbolRegistry


@pytest.fixture
def offline(monkeypatch):
    """NSE and niftyindices refuse every download, as they often do for a new cloud server."""

    def refuse(*args, **kwargs):
        raise requests.ConnectionError("blocked in test")

    class Session:
        get = staticmethod(refuse)

    monkeypatch.setattr(symbols.requests, "get", refuse)
    monkeypatch.setattr(symbols, "_nse_session", Session)


def test_bundled_snapshot_serves_a_new_server_that_nse_refuses(tmp_path, offline):
    registry = SymbolRegistry(tmp_path)
    assert registry.lot_sizes()["NIFTY"] > 0
    assert "RELIANCE" in registry.equities()
    meta = registry.meta("RELIANCE")
    assert meta.option_type == "Equity" and meta.lot_size and meta.sector
    status = registry.reference_status["fo_mktlots.csv"]
    assert status["source"] == "bundled snapshot" and status["as_of"] == symbols.seed_date()
    assert "download failed" in status["detail"]


def test_last_downloaded_copy_beats_the_bundled_snapshot(tmp_path, offline):
    path = tmp_path / "fo_mktlots.csv"
    path.write_text((SEED_DIR / "fo_mktlots.csv").read_text(encoding="utf-8"), encoding="utf-8")
    three_days_ago = time.time() - 3 * 86400
    os.utime(path, (three_days_ago, three_days_ago))
    registry = SymbolRegistry(tmp_path)
    registry.lot_sizes()
    assert registry.reference_status["fo_mktlots.csv"]["source"] == "stale cache"


def test_stale_lists_are_retried_instead_of_kept_forever(tmp_path, offline, monkeypatch):
    registry = SymbolRegistry(tmp_path)
    registry.lot_sizes()
    calls = []
    monkeypatch.setattr(registry, "_cached_text", lambda *args: calls.append(args) or (SEED_DIR / "fo_mktlots.csv").read_text(encoding="utf-8"))
    registry.lot_sizes()
    assert not calls  # within the retry interval the parsed copy is reused
    name = "fo_mktlots.csv"
    loaded_at, value = registry._parsed[name]
    registry._parsed[name] = (loaded_at - symbols.RETRY_SECONDS - 1, value)
    registry.lot_sizes()
    assert len(calls) == 1


def test_search_puts_the_exact_symbol_first(tmp_path, offline):
    registry = SymbolRegistry(tmp_path)
    results = registry.search("RELIANCE")
    assert results[0]["symbol"] == "RELIANCE"  # not a company whose name merely contains "Reliance"
    assert registry.search("NIFTY")[0]["symbol"] == "NIFTY"
    assert [r["symbol"] for r in registry.search("TCS")][:1] == ["TCS"]


def test_a_list_missing_everywhere_is_unavailable(tmp_path, offline, monkeypatch):
    monkeypatch.setattr(symbols, "SEED_DIR", tmp_path / "no-seed")
    with pytest.raises(DataUnavailable):
        SymbolRegistry(tmp_path / "cache").equities()


def test_health_reports_reference_data(client):
    names = [c["name"] for c in client.get("/api/health").json()["components"]]
    assert "Reference data" in names
