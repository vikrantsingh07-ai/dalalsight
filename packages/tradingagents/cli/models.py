from enum import Enum


class AnalystType(str, Enum):
    MARKET = "market"
    # Wire value stays "social" for saved-config and string-keyed-caller
    # back-compat; the user-facing label is "Sentiment Analyst".
    SOCIAL = "social"
    NEWS = "news"
    FUNDAMENTALS = "fundamentals"
    # Indian F&O positioning; offered only for instruments with exchange derivatives.
    DERIVATIVES = "derivatives"


class AssetType(str, Enum):
    STOCK = "stock"
    CRYPTO = "crypto"
    # Indian market segments (see tradingagents/dataflows/india/instruments.py).
    INDEX = "index"
    FUTURES = "futures"
    OPTIONS = "options"
    COMMODITY = "commodity"
    CURRENCY = "currency"
