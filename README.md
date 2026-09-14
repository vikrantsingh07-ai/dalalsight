# AI Trading Command Center

A research and decision-support platform for Indian markets (NSE/BSE indices, stocks, F&O). It combines:
- a live analysis dashboard
- transparent signal, options and risk engines
- **TradingAgents India**, a team of LLM analysts, with their bull/bear debate and portfolio decision

It is one repository with one Python environment.

> Research and decision support only, not investment advice. Real order execution is disabled; paper trading only.
> Missing or weak evidence gives **NO TRADE / WAIT FOR CONFIRMATION**. Data is never invented.

## What's inside

| Part | Folder | What it does |
|---|---|---|
| Backend API | `backend/cc` | FastAPI server with data providers, analysis engines, AI layer, market monitor, alerts, paper trading, backtests, REST + WebSocket |
| Dashboard | `web/` | React 19 + TypeScript + Tailwind with 13 pages and a voice assistant. Deployable to Vercel. |
| Agent engine | `packages/tradingagents` | TradingAgents extended for NSE/BSE, F&O, MCX and currencies ([UPSTREAM.md](packages/tradingagents/UPSTREAM.md)) |
| TradingView | `tradingview/` | The signal engine as a Pine Script v6 indicator for your TradingView app |
| Docs | `docs/` | [How it works](docs/HOW_IT_WORKS.md) · [Deployment (Vercel + backend)](docs/DEPLOYMENT.md) · design notes |
| Container | `Dockerfile` | API + built dashboard in one image for an always-on backend host |

```text
ai-trading-command-center/
├── backend/
│   ├── cc/
│   │   ├── api/            FastAPI app, routes, security, service container
│   │   ├── data/           MarketDataProvider: NSE, Yahoo, composite routing, broker slots, market hours
│   │   ├── analysis/       indicators, levels, events, regime, signal engine, options, strategies, hedging, scanner, backtest
│   │   ├── agents/         model manager, TradingAgents adapter, commentary, assistant
│   │   ├── orchestration/  analysis snapshots, stock service, multi-agent runs + consensus
│   │   ├── services/       monitor loop, alerts, notifiers, signals, paper trading, replay, backtests, health
│   │   └── storage/        SQLite (WAL) + migrations
│   └── tests/              offline tests (fake providers)
├── web/                    dashboard (Vite) + vercel.json
├── packages/tradingagents/ multi-agent LLM engine (India edition)
├── tradingview/            command_center_signal_engine.pine
├── docs/
├── Dockerfile
├── .env.example
└── pyproject.toml
```

## Quick start (Windows)

```bash
git clone https://github.com/vikrantsingh07-ai/ai-trading-command-center.git
cd ai-trading-command-center
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e packages/tradingagents -e ".[dev]"
cd web && npm ci && npm run build && cd ..
copy .env.example .env
```

Put your `OPENROUTER_API_KEY` in `.env`, then start:

```bash
.venv/Scripts/python.exe -m cc
```

Open http://127.0.0.1:8765. One process serves the API, the WebSocket channel and the built dashboard.

**Frontend hot reload:** keep the backend running, run `cd web && npm run dev`, and open http://localhost:5173. It proxies `/api`
and `/ws` to port 8765.

**TradingAgents CLI** (full research report for one symbol): run `tradingagents` with `TRADINGAGENTS_MARKET=india` in `.env`.

## How it works (short)

1. **Data:** the `MarketDataProvider` interface gets quotes, bars, option chains and market status from NSE's public API and Yahoo
   Finance. Every value carries its source and timestamp. When a feed fails, the UI says "Data unavailable" and
   never shows a guessed number.
2. **Analysis:**
   - Causal indicators, support/resistance, events (crosses, breakouts, level tests), market regime and option-chain analytics feed the **signal engine**.
   - Signal engine component weights: trend 20, momentum 15, volume 15, EMA structure 15, VWAP 10, market structure 15, volatility 5, options 5.
   - Composite `S = Σwᵢsᵢ / Σwᵢ` over the components that have data.
   - Bullish scenario = `50 + 50·S`. Confidence = agreeing weight ÷ available weight × coverage.
   - Trade plans derive entry, stop and targets from ATR and detected levels.
3. **Monitor:** a background loop refreshes the watched indices every 30 s during market hours. It records signals, fires
   alerts (dashboard, sound, voice, Telegram, email, webhook) and pushes updates to the dashboard over WebSocket.
4. **AI:**
   - The model manager uses a 550B default model with a 120B fallback, cooldowns and a daily call budget.
   - It rejects AI text that contains numbers missing from the facts it was given.
   - Commentary is event-driven. The assistant answers in 9 fixed sections.
   - **Agent runs** execute the TradingAgents analysts (market, sentiment, news, fundamentals, F&O) and combine them into a consensus.
5. **Charts:** charts open in TradingView itself, because TradingView embeds cannot show NSE/BSE data. The Pine Script indicator puts
   the same signals, levels and alerts on your TradingView chart.

Full walkthrough with diagrams: [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).

## Deployment

The dashboard deploys to **Vercel** (`web/`, set `VITE_API_BASE_URL`). The backend needs an **always-on server**: it runs a
continuous monitor loop, keeps WebSocket connections, stores SQLite data and runs 10-minute agent jobs, and Vercel
Functions don't support that. Use a VPS or a Docker host with `CC_ACCESS_TOKEN` and `CC_CORS_ORIGINS` set. Step by step:
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Environment variables

Copy `.env.example` to `.env`; process environment variables always win. Secrets never reach the browser.

| Variable | Purpose | Default |
|---|---|---|
| `CC_HOST`, `CC_PORT` (or `PORT`) | bind address | `127.0.0.1`, `8765` |
| `CC_ACCESS_TOKEN` | token for API + WebSocket; **required** when not bound to localhost | empty |
| `CC_CORS_ORIGINS` | dashboard origins allowed cross-origin (e.g. your Vercel URL) | empty |
| `CC_DEV_MODE` | allow the Vite dev server origin | `true` |
| `CC_DB_PATH` | SQLite file | `data/command_center.db` |
| `AI_PROVIDER`, `AI_BASE_URL`, `AI_API_KEY` / `AI_API_KEY_ENV` | OpenAI-compatible provider | `openrouter`, OpenRouter URL, `OPENROUTER_API_KEY` |
| `DEFAULT_AI_MODEL`, `FALLBACK_AI_MODEL` | preferred / fallback models | NVIDIA Nemotron 550B / 120B (free) |
| `AI_TIMEOUT_SECONDS`, `AI_DAILY_CALL_BUDGET`, `AI_MODEL_COOLDOWN_SECONDS` | call limits | `120`, `45`, `600` |
| `MARKET_DATA_PROVIDER` | `public`, or `kite`/`upstox`/`dhan` (adapters not implemented) | `public` |
| `EXECUTION_MODE`, `LIVE_EXECUTION_ENABLED` | analysis/paper; live is refused | `analysis`, `false` |
| `TELEGRAM_*`, `ALERT_WEBHOOK_URL`, `SMTP_*`, `ALERT_EMAIL_*` | alert channels | empty |
| `TRADINGAGENTS_MARKET`, `TRADINGAGENTS_LLM_PROVIDER`, `TRADINGAGENTS_QUICK_THINK_LLM`, `TRADINGAGENTS_DEEP_THINK_LLM` | TradingAgents India settings | `india`, `openrouter`, 120B, 550B |
| `VITE_API_BASE_URL`, `VITE_WS_URL` | dashboard build-time: where the API lives when hosted separately | same origin |

User-editable settings (weights, thresholds, market hours, voice, monitor symbols, risk) live in the Settings page and
are validated and stored in SQLite.

## Data sources and entitlements

| Need | Source | Notes |
|---|---|---|
| Index quotes, breadth, session status, holidays | NSE public website API | unofficial; failures surface as "Data unavailable" |
| Index intraday bars | Yahoo (1m–1h), plus NSE 1-second ticks merged for the current session | spot indices have **no volume**, so the VWAP/volume components are unavailable |
| Stock quotes/bars, fundamentals | Yahoo Finance | delay not guaranteed |
| Option chains | NSE `option-chain-v3` | OI, volume, bid/ask, IV; Greeks via Black-Scholes |
| Futures volume/VWAP, real-time ticks, SPAN margin, execution | broker API | **not available**: needs broker credentials + adapter |

## TradingView indicator

`tradingview/command_center_signal_engine.pine` is also served at `/api/tradingview/pine` and copyable from the Dashboard.

1. TradingView app → Pine Editor → Open → New indicator → paste → Save → Add to chart.
2. Use futures charts (`NSE:NIFTY1!`, `NSE:BANKNIFTY1!`) for the volume and VWAP components.
3. Alerts → Create → Condition "CC Engine" → e.g. "CC: Bullish setup" → "Once per bar close".

## Tests and checks

```bash
.venv/Scripts/python.exe -m pytest                                  # Command Center backend (offline)
.venv/Scripts/python.exe -m ruff check backend
.venv/Scripts/python.exe -m mypy
cd web && npm run build && npx oxlint                               # type-check, bundle, lint
cd packages/tradingagents && ../../.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider   # TradingAgents India
```

## Known limitations

- **TradingView:** embeds cannot display NSE/BSE symbols, so charts open in TradingView itself.
- **NSE data:** the public endpoints are unofficial, may throttle or change, and often reject cloud data-center IPs.
- **AI limits:** free OpenRouter models are slow and rate limited. One TradingAgents analyst takes about 10 minutes, and the daily budget is enforced.
- **Data that fills in over time:**
  - IV percentile needs at least 20 stored daily snapshots.
  - Signal outcome statistics accumulate from live use.
