# Existing system (Phase 1–3 inspection, 2026-09-13)

Two independent applications live under `D:\DalalSight`. DalalSight builds on the
second one and must not break either.

## 1. Momentum Bot (crypto) — `D:\DalalSight`

| Area | What exists |
|---|---|
| Purpose | EMA 9/21 + RSI momentum strategy on CoinDCX spot (BTC/ETH/SOL/DOGE vs USDT, 5m), DEMO (paper) mode only |
| Backend | FastAPI (`bot/api`), session-cookie auth, WebSocket push, SQLAlchemy + SQLite (`bot_data.db`: 56 signal_log rows) |
| Engine | `bot/core` indicators/strategy/risk/portfolio, `bot/engine` no-lookahead backtester + live runner, `bot/exchange` CoinDCX + Binance history + PaperBroker |
| Frontend | `web/` React 19 + Vite 8 + TypeScript 6 + Tailwind 4 (6 screens), served from `web/dist` |
| Ports | backend 8000, Vite dev 5173 |
| Tests | `pytest bot/tests` → **94 passed** |

DalalSight does not modify this app. It reuses the same frontend stack for consistency
and runs on a different port (8765).

## 2. TradingAgents (multi-agent LLM system) — `D:\DalalSight\TradingAgents`

TauricResearch TradingAgents (LangGraph), locally extended for Indian markets
(`tradingagents/dataflows/india/`). Pipeline:

```
Analyst team (5)  →  Bull/Bear researchers  →  Research Manager  →  Trader
                  →  Aggressive/Conservative/Neutral risk debate  →  Portfolio Manager
```

### The five existing agents (the analyst team)

| # | Key | Agent | Tools (data) | Output |
|---|---|---|---|---|
| 1 | `market` | Market Analyst | OHLCV, stockstats indicators, verified snapshot, NSE delivery % | `market_report` (prose + table) |
| 2 | `social` | Sentiment Analyst | Google News India / Yahoo news, StockTwits, Reddit (pre-fetched) | `sentiment_report` (structured band/score/confidence + narrative) |
| 3 | `news` | News Analyst | instrument news, India macro headlines, FRED (optional key), Polymarket, FII/DII cash flows | `news_report` |
| 4 | `fundamentals` | Fundamentals Analyst | yfinance statements, NSE index valuation, NSE corporate events | `fundamentals_report` |
| 5 | `derivatives` | Derivatives (F&O) Analyst | NSE/BSE F&O bhavcopy (futures, option chain), participant OI, India VIX | `derivatives_report` |

All five are LLM tool-calling agents that produce prose reports on daily/EOD data. They run
through OpenRouter (`OPENROUTER_API_KEY` in `TradingAgents/.env`); a full run takes 10–20
minutes on free NVIDIA models.

### Data sources verified live

| Source | Works | Notes |
|---|---|---|
| Yahoo Finance (yfinance) | quotes, OHLCV 1m (7d), 5m/15m/30m (60d), 1h (~3y), 1d, 1wk; batch download | **Indices have zero volume**; FINNIFTY feed stale since 2026-07-17; MIDCPNIFTY/BANKEX 1 row |
| NSE public site API | `marketStatus`, `allIndices` (live index OHLC + breadth), `chart-databyindex-dynamic` (1-second index ticks), `option-chain-v3` + `option-chain-contract-info` (live chain with IV, OI, bid/ask), `holiday-master`, `historicalOR/indicesHistory`, `equity-stock-indices` | `quote-equity` is blocked (403). Unofficial, rate-limited, no SLA |
| NSE archives | F&O bhavcopy, participant OI, security-wise delivery, index closes, `EQUITY_L.csv`, `fo_mktlots.csv` | end-of-day |
| niftyindices.com | index constituents CSV (with industry) | daily |
| OpenRouter | free NVIDIA Nemotron models | Ultra 550B frequently overloaded (HTTP 502) and slow; Super 120B reliable |

## 3. Bugs and gaps found (Phase 3)

| # | Bug | Root cause | Fix and status |
|---|---|---|---|
| B1 | `tradingagents.exe` CLI runs old code without any India support | package installed non-editable (`pip install .`), CLI imports the site-packages copy | **Fixed**: reinstalled editable; CLI verified importing the local source |
| B2 | FINNIFTY price history stale (last row 2026-07-17) | Yahoo `NIFTY_FIN_SERVICE.NS` daily feed stopped updating | **Fixed**: `dataflows/india/index_history.py` rebuilds stale/sparse NSE index history from NSE (`load_ohlcv`, `get_YFin_data_online`); tested |
| B3 | MIDCPNIFTY / BANKEX price history has 1 row | Yahoo has no history for these symbols | **Fixed** for MIDCPNIFTY (NSE fallback); BANKEX remains a documented limitation |
| B4 | Quarterly cash flow returns NO_DATA for RELIANCE, HDFCBANK | Yahoo publishes only annual cash flow for many Indian companies | **Fixed**: annual fallback with an explicit note; tested |
| B5 | Agents misread FII/DII flows ("DII absorbed <70%" when DII bought 2× FII selling) | LLM arithmetic on raw figures | **Fixed**: tool output states combined net and the computed coverage ratio; tested |
| B6 | Researchers/managers invented statistics not present in any tool output | prompts do not forbid external numbers | **Fixed**: `EVIDENCE_RULE` in bull/bear/research-manager/portfolio-manager prompts; tested |
| B7 | Ultra 550B model failures abort runs | provider overload returned in response body, not retried | **Fixed**: transient upstream errors retried in `NormalizedChatOpenAI`; DalalSight model manager adds cooldown + fallback; tested |
| B8 | CLI OpenRouter picker never lists NVIDIA models | picker whitelists mainstream namespaces | **Fixed**: `TRADINGAGENTS_LLM_PROVIDER` / `QUICK_THINK_LLM` / `DEEP_THINK_LLM` set in `TradingAgents/.env` |
| L1 | Index VWAP / volume analysis impossible from free data | spot indices carry no volume; intraday futures need a broker feed | **Handled**: components reported "Data unavailable"; broker provider slots name the credentials |
| L2 | BSE numeric scrip codes (e.g. `500325.BO`) stale on Yahoo | Yahoo feed | documented; use NSE symbols |

TradingAgents test suite after the fixes: **783 passed, 2 skipped**.

## 4. Bugs found and fixed while building DalalSight

| Bug | Root cause | Fix |
|---|---|---|
| Chart candles collapsed to 1970 | pandas 3 stores this index at a coarser unit than nanoseconds; `asi8 // 1e9` assumed ns | explicit `as_unit("s")`; test pins candle epoch seconds |
| `DELETE`/`UPDATE` reported success for missing rows | `execute` returned `lastrowid` for every statement | rows affected for non-INSERT statements; CRUD test |
| Backtest R:R worse than the signal plans | entries at next open ignored the plan's entry zone | limit entry at zone midpoint within N bars, R on planned risk; tests |
| 5% OTM hedge put picked from outside the strike window | nearest strike chosen from a ±15-strike table | wider hedge chain window + one-step tolerance; tests |
| Option recommendations/strategy suggestions requested with empty timeframe | settings not loaded on first render | request only when timeframe is known |
| Health showed data OFFLINE before first use | idle feeds counted as offline | idle feeds excluded from the aggregate |
| Agent runs could hang for minutes on a stalled free-tier request | client default timeout | bounded timeout + one retry; LangChain errors cool the model down; interrupted runs marked failed on restart |
| Analyst kept calling the model past its round cap | upstream "overloaded" retries happen inside one graph node; LangGraph checks its limit only between nodes | model-call cap and wall-clock budget enforced from the LangChain callback |
| An analyst stopped by its cap lost all gathered data | graph invoked without streaming, so no partial state | stream the state; finalise the report from the collected tool outputs and flag figures not found in them |
| Analyst failed outright when the default model timed out | no per-analyst fallback | one retry on the fallback model for transient provider errors, within the same budget |
| Structured extraction failed on malformed JSON from free models | strict parsing | tolerant parser (fences, trailing commas) + one corrective retry with the parse error |
