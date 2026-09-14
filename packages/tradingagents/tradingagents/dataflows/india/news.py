"""Indian market news from Google News' public RSS search (India edition).

Yahoo Finance's news search ignores regional queries and returns US-centric
trending stories, so Indian runs would otherwise analyse US gasoline prices and
Treasury yields. Google News' RSS search (``hl=en-IN``, ``gl=IN``) returns Indian
publishers (Moneycontrol, Economic Times, Mint, BusinessLine, Reuters India) with
publication timestamps and supports ``after:`` / ``before:`` operators, so a
historical run fetches its own analysis window instead of today's news. Items
are also filtered by timestamp, keeping the result look-ahead safe. No API key.
"""

from __future__ import annotations

import functools
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests
import yfinance as yf

from ..config import get_config
from ..date_window import in_window
from ..errors import NoMarketDataError
from .instruments import INDICES, IndianInstrument, parse_indian_symbol

logger = logging.getLogger(__name__)

_RSS_URL = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
_UA = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"
_MAX_FEED_BYTES = 5 * 1024 * 1024

# Names Indian financial media actually use for the derivative indices.
_INDEX_QUERY_NAMES = {
    "NIFTY": "Nifty",
    "BANKNIFTY": "Bank Nifty",
    "FINNIFTY": "Fin Nifty",
    "MIDCPNIFTY": "Nifty Midcap Select",
    "SENSEX": "Sensex",
    "BANKEX": "Bankex",
    "INDIAVIX": "India VIX",
}
_CURRENCY_QUERY_NAMES = {
    "USDINR": "rupee dollar",
    "EURINR": "rupee euro",
    "GBPINR": "rupee pound",
    "JPYINR": "rupee yen",
}
_COMPANY_SUFFIX_RE = re.compile(r"\b(ltd\.?|limited|corporation|corp\.?|inc\.?|plc)\s*$", re.IGNORECASE)
_CONTRACT_SIZE_RE = re.compile(r"\s+(Mini|Micro|Petal|Guinea|Ten)$")


def fetch_google_news(query: str, start_date: str, end_date: str, limit: int) -> list[dict]:
    """Articles matching ``query`` published within [start_date, end_date], newest first."""
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    # ``before:`` is exclusive, so ask for the day after the window ends.
    before = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    windowed = f"{query} after:{start_date} before:{before}"
    resp = requests.get(
        _RSS_URL.format(query=quote_plus(windowed)), headers={"User-Agent": _UA}, timeout=15
    )
    resp.raise_for_status()
    if len(resp.content) > _MAX_FEED_BYTES:
        raise ValueError("Google News feed exceeded the size cap; refusing to parse")
    root = ET.fromstring(resp.content)

    articles = []
    seen_titles: set[str] = set()
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        # Google appends " - <publisher>" to every headline.
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].rstrip()
        published = None
        raw_date = item.findtext("pubDate")
        if raw_date:
            try:
                published = parsedate_to_datetime(raw_date)
            except (TypeError, ValueError):
                published = None
        # An undated item is kept only for a live window (in_window's rule).
        if not title or not in_window(published, start_dt, end_dt):
            continue
        # Syndicated stories repeat under different links.
        if title.lower() in seen_titles:
            continue
        seen_titles.add(title.lower())
        articles.append({
            "title": title,
            "source": source or "Unknown",
            "published": published,
            "link": (item.findtext("link") or "").strip(),
        })
    articles.sort(key=lambda a: a["published"].timestamp() if a["published"] else 0.0, reverse=True)
    return articles[:limit]


def _format(articles: list[dict], heading: str) -> str:
    # Google News links are long opaque redirects that tell an agent nothing,
    # so only headline, publisher and date go into the prompt.
    lines = [heading, ""]
    for article in articles:
        stamp = article["published"].strftime("%Y-%m-%d") if article["published"] else "undated"
        lines.append(f"### {article['title']} (source: {article['source']}, {stamp})")
    return "\n".join(lines) + "\n"


@functools.lru_cache(maxsize=256)
def _company_name(yahoo_symbol: str) -> str | None:
    """Short company name for a news query (``HDFCBANK.NS`` -> ``HDFC BANK``), or None."""
    try:
        info = yf.Ticker(yahoo_symbol).info or {}
    except Exception:  # noqa: BLE001 — the bare symbol is a usable fallback query
        return None
    name = str(info.get("shortName") or info.get("longName") or "").strip()
    name = _COMPANY_SUFFIX_RE.sub("", name).strip(" .,")
    return name or None


def news_query(inst: IndianInstrument) -> str | None:
    """Search query Indian media coverage of ``inst`` matches, or None if there is no good one."""
    if inst.underlying_kind == "index":
        return f'"{_INDEX_QUERY_NAMES.get(inst.underlying) or INDICES[inst.underlying].name}"'
    if inst.underlying_kind == "commodity":
        return f"MCX {_CONTRACT_SIZE_RE.sub('', inst.name or inst.underlying)} price"
    if inst.underlying_kind == "currency":
        return _CURRENCY_QUERY_NAMES.get(inst.underlying, inst.underlying)
    if inst.exchange != "NSE":
        return None  # BSE scrip codes make poor queries; Yahoo handles them
    name = _company_name(f"{inst.underlying}.NS")
    return f'"{name}" share' if name else f"{inst.underlying} share"


def get_news_india(ticker: str, start_date: str, end_date: str) -> str:
    """Instrument news for an Indian ticker; raises NoMarketDataError for anything else."""
    inst = parse_indian_symbol(ticker)
    query = news_query(inst) if inst is not None else None
    if query is None:
        raise NoMarketDataError(ticker, None, "Google News India covers NSE/MCX/INR instruments only")
    articles = fetch_google_news(query, start_date, end_date, get_config()["news_article_limit"])
    if not articles:
        return f"No news found for {ticker} ({query}) between {start_date} and {end_date}"
    return _format(
        articles, f"## {ticker} News (query {query}, Google News India), from {start_date} to {end_date}:"
    )


def get_global_news_india(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> str:
    """Indian macro and market headlines for the configured ``global_news_queries``."""
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]
    start_date = (datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=look_back_days)).strftime("%Y-%m-%d")

    per_query: list[list[dict]] = []
    failures: list[Exception] = []
    for query in config["global_news_queries"]:
        try:
            per_query.append(fetch_google_news(query, start_date, curr_date, limit))
        except (requests.RequestException, ET.ParseError, ValueError) as exc:
            logger.warning("Google News query %r failed: %s", query, exc)
            failures.append(exc)
    if failures and not per_query:
        raise failures[0]  # nothing reachable: let the router try the next vendor

    # Round-robin across queries so one busy topic cannot crowd out the rest.
    seen: set[str] = set()
    merged: list[dict] = []
    for rank in range(max((len(a) for a in per_query), default=0)):
        for articles in per_query:
            if rank < len(articles) and articles[rank]["title"].lower() not in seen:
                seen.add(articles[rank]["title"].lower())
                merged.append(articles[rank])
    merged = merged[:limit]
    if not merged:
        return f"No Indian market headlines found between {start_date} and {curr_date}"
    merged.sort(key=lambda a: a["published"].timestamp() if a["published"] else 0.0, reverse=True)
    return _format(merged, f"## Indian Market News (Google News India), from {start_date} to {curr_date}:")
