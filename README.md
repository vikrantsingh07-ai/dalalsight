# AI Trading Command Center

A local, single-user trading research dashboard for Indian markets (NSE/BSE indices, stocks, F&O)
built on top of the existing five-agent TradingAgents system. The dashboard runs in Chrome at
**http://127.0.0.1:8765**.

> Research and decision support only — not investment advice. Real order execution is disabled.

## Start

```bash
cd "D:/Crypto Algo/command_center"
.venv/Scripts/python.exe -m cc
```

Then open http://127.0.0.1:8765 in Chrome. One process serves the API, the WebSocket push channel and
the built dashboard.

First-time setup (already done on this machine):

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e "../TradingAgents" -e ".[dev]"
cd web && npm install && npm run build
```

Frontend development with hot reload: run the backend as above, then `cd web && npm run dev` and open
http://localhost:5173 (proxies `/api` and `/ws` to port 8765).

## Architecture

| Layer | Package | Responsibility |
|---|---|---|
| Data | `backend/cc/data` | `MarketDataProvider` interface (`get_quote`, `get_ohlcv`, `get_option_chain`, `get_expiries`, `get_instrument_metadata`, `get_market_status`); Yahoo + NSE public providers; composite routing with provenance; broker feed slots (Kite, Upstox, Dhan) that report missing credentials; TTL cache; symbol registry; IST market calendar |
| Analysis | `backend/cc/analysis` | causal indicators, technical events, support/resistance, market regime, signal confidence engine, option-chain analytics + Greeks, strategy builder, hedging, stock scanner/scores, walk-forward backtest |
| Agents | `backend/cc/agents` | model manager (default/fallback model, cooldowns, daily budget), TradingAgents adapter (the five analysts run unchanged), event-driven commentary, grounded assistant |
| Orchestration | `backend/cc/orchestration` | analysis snapshots, option/stock services, multi-agent runs + consensus |
| Services | `backend/cc/services` | market monitor loop, alerts + notifiers, signal history, paper trading, replay, backtest jobs, health, timeline, event bus |
| Storage | `backend/cc/storage` | SQLite (WAL) with versioned migrations |
| API | `backend/cc/api` | FastAPI REST + `/ws`, optional access token, rate limits, NaN-safe JSON |
| Web | `web/` | React 19 + TypeScript + Tailwind 4; no charts of its own ("Open in TradingView" links); Web Speech API voice |
| TradingView | `tradingview/` | the signal engine as a Pine Script v6 indicator for your own TradingView app |

Signal model: each component (trend 20, momentum 15, volume 15, EMA structure 15, VWAP 10, market
structure 15, volatility 5, options 5 — configurable) scores −1…+1 with evidence. Composite
S = Σwᵢsᵢ / Σwᵢ over components that have data; bullish scenario = 50 + 50·S; model confidence =
agreeing weight ÷ available weight × coverage. Insufficient coverage, confidence or agreement
yields **NO TRADE / WAIT FOR CONFIRMATION**. Trade plans derive entry/stop/targets from ATR and detected
levels and state the basis of every value.

## Environment variables

Copy `.env.example` to `.env`. The server also reads `../TradingAgents/.env` (shared provider keys);
process environment variables always win. Secrets never reach the browser.

| Variable | Purpose | Default |
|---|---|---|
| `CC_HOST`, `CC_PORT` | bind address | `127.0.0.1`, `8765` |
| `CC_DB_PATH` | SQLite file | `data/command_center.db` |
| `CC_DEV_MODE` | allow Vite dev server origin (CORS) | `true` |
| `CC_ACCESS_TOKEN` | optional token for API/WebSocket | empty (off) |
| `AI_PROVIDER`, `AI_BASE_URL` | OpenAI-compatible provider | `openrouter`, `https://openrouter.ai/api/v1` |
| `AI_API_KEY` or the env named by `AI_API_KEY_ENV` | provider key | `OPENROUTER_API_KEY` |
| `DEFAULT_AI_MODEL` | preferred (550B-class) model | `nvidia/nemotron-3-ultra-550b-a55b:free` |
| `FALLBACK_AI_MODEL` | used when the default is unlisted/overloaded | `nvidia/nemotron-3-super-120b-a12b:free` |
| `AI_TIMEOUT_SECONDS`, `AI_DAILY_CALL_BUDGET`, `AI_MODEL_COOLDOWN_SECONDS` | call limits | `120`, `45`, `600` |
| `MARKET_DATA_PROVIDER` | `public`, or `kite`/`upstox`/`dhan` (adapters not implemented) | `public` |
| `MARKET_DATA_API_KEY`, `MARKET_DATA_API_SECRET`, `MARKET_DATA_ACCESS_TOKEN` | broker feed credentials | empty |
| `TRADINGVIEW_WIDGET_ENABLED` | show the "Open in TradingView" links | `true` |
| `TRADINGVIEW_CHARTING_LIBRARY_PATH` | licensed Charting Library (not bundled) | empty |
| `EXECUTION_MODE`, `LIVE_EXECUTION_ENABLED` | analysis/paper/live; live refused | `analysis`, `false` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram alerts | empty |
| `ALERT_WEBHOOK_URL` | webhook alerts | empty |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO` | email alerts | empty |

User-editable settings (weights, thresholds, market hours, voice, monitor symbols, risk, etc.) live in
the Settings page and are validated and stored in SQLite.

## Data sources and entitlements

| Need | Source | Notes |
|---|---|---|
| Index quotes, breadth, session status, holidays | NSE public website API | unofficial; failures surface as "Data unavailable" |
| Index intraday bars | Yahoo (1m–1h); NSE 1-second ticks merged for the current session | spot indices have **no volume** → VWAP/volume components unavailable |
| Stock quotes/bars, fundamentals | Yahoo Finance (yfinance) | delay not guaranteed; fundamentals vendor-reported |
| Option chains | NSE `option-chain-v3` | OI, volume, bid/ask, IV; Greeks via Black-Scholes |
| Index futures volume/VWAP, real-time ticks, SPAN margin, order execution | broker API | **not available**; requires broker credentials + adapter |

## TradingView indicator

Charts are TradingView only. TradingView does not show NSE/BSE data inside embedded widgets
(exchange licensing), so the dashboard links out to TradingView's own chart for the selected symbol
and timeframe instead of embedding one. To see the Command Center's signals, levels and trade plan on
your TradingView chart, add `tradingview/command_center_signal_engine.pine` (also served at
`/api/tradingview/pine` and copyable from the Dashboard):

1. TradingView app → chart → Pine Editor → Open → New indicator.
2. Select all, paste the script, Save, Add to chart.
3. Use futures charts (`NSE:NIFTY1!`, `NSE:BANKNIFTY1!`) for the volume and VWAP components; spot
   indices carry no volume.
4. Alerts → Create → Condition "CC Engine" → e.g. "CC: Bullish setup" → "Once per bar close".

The indicator runs on TradingView's data, so its numbers can differ slightly from the dashboard
panels, which use the NSE/Yahoo feed. There is no option-chain data in Pine, so the options weight
counts as unavailable there.

## Tests and checks

```bash
.venv/Scripts/python.exe -m pytest          # backend tests (no network, fake providers)
.venv/Scripts/python.exe -m ruff check backend
.venv/Scripts/python.exe -m mypy
cd web && npm run build && npx oxlint       # type-check, bundle, lint
```

## Known limitations

* TradingView embeds cannot display NSE/BSE symbols, so there is no chart inside the dashboard; charts
  open in TradingView, and on-chart signals come from the Pine Script indicator in your TradingView app.
* NSE public endpoints are unofficial and may throttle or change.
* Free OpenRouter models are rate limited; the daily budget is enforced and shown in System Health.
* IV percentile needs ≥ 20 stored daily snapshots, so it fills in over time.
* Signals are recorded only during market hours; outcome statistics accumulate from live use.
