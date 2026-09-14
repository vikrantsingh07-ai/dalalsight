# DalalSight — implementation plan

Decisions below come from the Phase 1–3 inspection (`EXISTING_SYSTEM.md`). The guiding rule:
accuracy, transparency and auditability over signal volume. Nothing is simulated except
clearly-labelled PAPER trading and REPLAY of recorded sessions.

## Placement and runtime

```
D:\DalalSight\dalalsight\
  backend/cc/        FastAPI app + engines (Python 3.12, own .venv, TradingAgents installed editable)
  backend/tests/     pytest (no network; fake providers)
  web/               React 19 + Vite + TypeScript + Tailwind 4 + TradingView Lightweight Charts
  docs/              this plan, architecture, existing-system notes
  data/              SQLite database (signals, alerts, settings, logs)
```

One process: `uvicorn cc.api.app:app --host 127.0.0.1 --port 8765` serves the API, WebSocket
and the built frontend. Chrome URL: `http://127.0.0.1:8765`.

## Layers

| Layer | Package | Responsibility |
|---|---|---|
| Data | `cc.data` | `MarketDataProvider` interface; `YahooProvider`, `NSEPublicProvider`, `CompositePublicProvider`; broker stubs (Kite, Upstox, Dhan) that report the credentials they need; TTL cache; symbol registry; market hours |
| Analysis | `cc.analysis` | indicators, technical events, support/resistance, market regime, signal confidence engine, options analytics, strategy engine, hedging engine, scanner/scoring, backtester |
| Agent | `cc.agents` | model manager (default + fallback + budget), adapter running the five TradingAgents analysts, commentary agent, conversational assistant |
| Orchestration | `cc.orchestration` | runs agents, normalises to the shared schema, consensus + conflicts, activity timeline |
| Services | `cc.services` | market monitor loop, alerts + notifiers, paper trading, health registry, replay |
| Storage | `cc.storage` | SQLite schema/migrations and repositories |
| Presentation | `cc.api` + `web/` | REST, WebSocket events, dashboard pages |

AI code never imports UI code; the UI only talks to REST/WebSocket.

## Data entitlement reality (drives several features)

| Need | Source used | Status |
|---|---|---|
| Index quotes, breadth | NSE `allIndices` | live during market hours (unofficial public API) |
| Index intraday bars | Yahoo 1m–1h, NSE 1-second ticks for the current session | available, **no volume** |
| Stock quotes / bars | Yahoo | available (latency measured and displayed, not assumed) |
| Option chain (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, F&O stocks) | NSE `option-chain-v3` | live, with IV, OI, bid/ask; Greeks computed (Black-Scholes) |
| Index futures volume / VWAP | broker feed | **not available** → components excluded, UI shows "Data unavailable" |
| Order execution | broker API | **disabled**; LIVE mode refuses |

## Signal confidence model (transparent, configurable)

Each component returns a directional score in [-1, +1], an availability flag and evidence:
Trend 20 · Momentum 15 · Volume 15 · EMA structure 15 · VWAP 10 · Market structure 15 ·
Volatility 5 · Options positioning 5.

* composite `S = Σ wᵢsᵢ / Σ wᵢ` over **available** components
* bullish scenario = `50 + 50·S`, bearish = `100 − bullish` ("model-estimated, based on current signals")
* model confidence = evidence weight agreeing with the direction ÷ available weight × data coverage
* labels: BULLISH SETUP / BEARISH SETUP / WATCH / HIGH-RISK SETUP / LOW-QUALITY SETUP /
  **NO TRADE / WAIT FOR CONFIRMATION** (forced when coverage or confidence is insufficient)
* trade plan (entry zone, stop, T1, T2, R:R) only for setups, derived from ATR and detected levels,
  each value tagged with its derivation
* every signal is stored; outcomes (hit T1/T2/stop, R multiple, MFE, MAE) are evaluated from later bars

## Agents and orchestration

* The five TradingAgents analysts run unchanged through a mini LangGraph (analyst ⇄ tools) with a
  live-dashboard snapshot appended to their instrument context.
* One structured-extraction call converts the five reports into the shared schema
  (`agent, timestamp, symbol, timeframe, signal, confidence, reasoning, levels, risk, data_sources`);
  confidence from LLM agents is labelled `llm_assessed`.
* Consensus = confidence-weighted direction vote; opposing agents listed with their reason.
* The full TradingAgents pipeline (debate → trader → portfolio manager) stays available as a job.

## Commentary and assistant

* Deterministic event detection on every market update; commentary only on material change
  (regime change, signal label change, confidence Δ ≥ 15, confirmed crossovers, breakouts,
  level tests, volume spikes, OI shifts), with global interval and per-event cooldowns.
* Priority LOW/MEDIUM/HIGH/CRITICAL; HIGH/CRITICAL are narrated by the LLM (budget permitting)
  and spoken; the LLM text is rejected if it contains numbers absent from the facts.
* No automatic commentary while the market is closed (REPLAY of a recorded session is labelled).
* Assistant answers from the current chart context (symbol, timeframe, expiry, strike) with the
  nine-part structure; falls back to an engine summary when the model or budget is unavailable.

## Model configuration

`DEFAULT_AI_MODEL` (550B-class, used when listed and healthy), `FALLBACK_AI_MODEL`, provider/base
URL/key env names, timeout, daily call budget. Overload/5xx/timeouts put the default model on a
cooldown and retry once on the fallback. Active model, availability and calls used are shown in
System Health.

## Phases

1–3 inspection ✔ · 4 fix B1–B8 in TradingAgents with tests · 5 data layer · 6 orchestration ·
7 dashboard shell · 8 charts (Lightweight Charts with internal indicators + official TradingView
Advanced Chart widget) · 9 regime/technical/levels/signal engines · 10 commentary · 11 assistant +
voice (Web Speech API) · 12 scanner + stock analysis · 13 options · 14 strategies + hedging ·
15 alerts · 16 health, logging, signal history, paper trading, backtest · 17 tests · 18 build ·
19 serve · 20 verify in Chrome.

## Known limitations accepted up front

* No licensed TradingView Charting Library: the Advanced Chart widget shows TradingView's own data
  and cannot feed the AI; internal analysis uses the backend provider (principle 26).
* Free OpenRouter tier limits AI calls per day; the budget is enforced and visible.
* NSE public endpoints are unofficial and may throttle or change; failures surface as
  "Data unavailable" and in System Health.
* Market closed on 2026-09-13 (Sunday) and 2026-09-14 (NSE holiday): live-market verification uses
  the last session's real data and REPLAY.
