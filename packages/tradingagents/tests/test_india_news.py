"""Indian news from Google News India RSS, and its routing (no network)."""

import pytest

from tradingagents.dataflows import interface
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.india import news
from tradingagents.dataflows.india.instruments import parse_indian_symbol
from tradingagents.default_config import DEFAULT_CONFIG, apply_market_preset

_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title>Nifty closes near 23,400 as FIIs sell - Moneycontrol.com</title><link>https://news.google.com/a1</link>
<pubDate>Fri, 11 Sep 2026 05:14:33 GMT</pubDate><source url="https://www.moneycontrol.com">Moneycontrol.com</source></item>
<item><title>Nifty closes near 23,400 as FIIs sell - Moneycontrol.com</title><link>https://news.google.com/a1-syndicated</link>
<pubDate>Fri, 11 Sep 2026 05:20:00 GMT</pubDate><source url="https://www.moneycontrol.com">Moneycontrol.com</source></item>
<item><title>Nifty slips below support - The Economic Times</title><link>https://news.google.com/a2</link>
<pubDate>Sat, 12 Sep 2026 08:45:44 GMT</pubDate><source url="https://economictimes.com">The Economic Times</source></item>
<item><title>Old story - BusinessLine</title><link>https://news.google.com/a3</link>
<pubDate>Mon, 01 Jun 2026 10:00:00 GMT</pubDate><source url="https://thehindubusinessline.com">BusinessLine</source></item>
</channel></rss>"""


class _Response:
    status_code = 200

    def __init__(self, content: str):
        self.content = content.encode()

    def raise_for_status(self):
        pass


@pytest.fixture
def feed(monkeypatch):
    urls = []

    def fake_get(url, headers=None, timeout=None):
        urls.append(url)
        return _Response(_FEED)

    monkeypatch.setattr(news.requests, "get", fake_get)
    return urls


@pytest.mark.unit
def test_fetch_filters_to_window_and_strips_publisher(feed):
    articles = news.fetch_google_news('"Nifty"', "2026-09-05", "2026-09-11", 10)
    assert [a["title"] for a in articles] == ["Nifty closes near 23,400 as FIIs sell"]
    assert articles[0]["source"] == "Moneycontrol.com"
    assert "after%3A2026-09-05+before%3A2026-09-12" in feed[0]
    assert "hl=en-IN" in feed[0]


@pytest.mark.unit
@pytest.mark.parametrize(
    "ticker,query",
    [
        ("NIFTY26SEPFUT", '"Nifty"'),
        ("BANKNIFTY-OPT", '"Bank Nifty"'),
        ("NIFTYIT", '"Nifty IT"'),
        ("HDFCBANK.NS", '"HDFC BANK" share'),
        ("GOLDM.MCX", "MCX Gold price"),
        ("CRUDEOIL26SEPFUT", "MCX Crude Oil price"),
        ("USDINR", "rupee dollar"),
        ("500325.BO", None),
    ],
)
def test_queries_by_segment(monkeypatch, ticker, query):
    monkeypatch.setattr(news, "_company_name", lambda symbol: "HDFC BANK")
    assert news.news_query(parse_indian_symbol(ticker)) == query


@pytest.mark.unit
def test_instrument_news_and_non_indian_rejection(feed, monkeypatch):
    monkeypatch.setattr(news, "_company_name", lambda symbol: None)
    out = news.get_news_india("RELIANCE.NS", "2026-09-05", "2026-09-12")
    assert "query RELIANCE share" in out
    assert "(source: The Economic Times, 2026-09-12)" in out
    assert out.count("Nifty closes near 23,400") == 1  # syndicated duplicate dropped
    assert "news.google.com" not in out  # opaque redirect links stay out of the prompt
    with pytest.raises(NoMarketDataError):
        news.get_news_india("AAPL", "2026-09-05", "2026-09-12")


@pytest.mark.unit
def test_global_news_merges_dedupes_and_sorts(feed):
    set_config({"global_news_queries": ["Sensex Nifty", "RBI"], "global_news_article_limit": 5})
    out = news.get_global_news_india("2026-09-12", 7)
    assert out.startswith("## Indian Market News (Google News India)")
    assert out.count("### ") == 2  # the same feed from both queries is de-duplicated
    assert out.index("slips below support") < out.index("closes near 23,400")
    assert len(feed) == 2


@pytest.mark.unit
def test_india_preset_routes_news_to_google_first():
    config = apply_market_preset({**DEFAULT_CONFIG, "market": "india"})
    assert config["data_vendors"]["news_data"] == "google_news,yfinance"
    assert DEFAULT_CONFIG["data_vendors"]["news_data"] == "yfinance"


@pytest.mark.unit
def test_router_falls_back_to_yahoo_for_other_markets(monkeypatch):
    set_config({"data_vendors": {"news_data": "google_news,yfinance"}})
    monkeypatch.setitem(interface.VENDOR_METHODS["get_news"], "yfinance", lambda *args: "yahoo news")
    assert interface.route_to_vendor("get_news", "AAPL", "2026-09-01", "2026-09-11") == "yahoo news"
