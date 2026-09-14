from helpers import FakeRegistry

from cc.data.cache import TTLCache
from cc.data.nse import NSEPublicProvider

PAYLOAD = {
    "timestamp": "11-Sep-2026 15:30",
    "advances": 3101,  # NSE's total adds every index row together
    "declines": 6430,
    "unchanged": 87,
    "data": [
        {"index": "NIFTY 50", "last": 23398.1, "advances": 12, "declines": 37, "unchanged": 1},
        {"index": "NIFTY 500", "last": 21500.0, "advances": 160, "declines": 336, "unchanged": 5},
    ],
}


def test_breadth_counts_each_nifty_500_stock_once(tmp_path, monkeypatch):
    provider = NSEPublicProvider(FakeRegistry(tmp_path), TTLCache())
    monkeypatch.setattr(provider, "_json", lambda path, params=None: PAYLOAD)
    breadth = provider.all_indices()["breadth"]
    assert (breadth["advances"], breadth["declines"], breadth["unchanged"]) == (160, 336, 5)
    assert breadth["basis"] == "NIFTY 500 stocks"


def test_breadth_falls_back_to_the_labelled_total(tmp_path, monkeypatch):
    provider = NSEPublicProvider(FakeRegistry(tmp_path), TTLCache())
    payload = {**PAYLOAD, "data": PAYLOAD["data"][:1]}
    monkeypatch.setattr(provider, "_json", lambda path, params=None: payload)
    breadth = provider.all_indices()["breadth"]
    assert breadth["advances"] == 3101 and "more than once" in breadth["basis"]
