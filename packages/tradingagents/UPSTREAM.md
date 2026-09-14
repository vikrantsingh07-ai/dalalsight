# TradingAgents India — upstream and changes

This folder is a vendored copy of [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
(Apache License 2.0, see `LICENSE`), extended for Indian markets. DalalSight imports it as the
`tradingagents` Python package:

```bash
pip install -e packages/tradingagents
```

| | |
|---|---|
| Upstream base | `be952b8`, "Merge pull request #1310 from TauricResearch/v0.4.2" (package version 0.4.0) |
| India adaptation | commit `b05384e` (branch `india-adaptation` of the original clone), vendored here on 14 Sep 2026 |
| Not copied | `.github/workflows/` (upstream CI, which does not apply inside this repository) |

The original clone, with its full git history, is kept locally outside this repository.

## Changes from upstream

**New**
- `tradingagents/dataflows/india/`:
  - `instruments.py`: parses NSE/BSE symbols and holds the index, MCX commodity and currency specs.
  - `nse_client.py`: NSE API and archive client with a disk cache.
  - `fno.py`: F&O bhavcopy, futures basis, option-chain analytics, Black-Scholes Greeks and IV, participant OI and India VIX.
  - `cash_market.py`: delivery data, corporate events, FII/DII flows and index fundamentals.
  - `news.py`: Google News India.
  - `commodities.py`: MCX proxy (global future × USDINR × unit factor; MCX blocks automated access).
  - `index_history.py`: NSE index history fallback when Yahoo data is stale or partial.
- `tradingagents/agents/analysts/derivatives_analyst.py`: the F&O analyst (key `derivatives`).
- `tradingagents/agents/utils/india_data_tools.py`: LangChain tools for the India data above.
- Tests: `tests/test_india_*.py`.

**Modified**
- `default_config.py`: `market` preset (`TRADINGAGENTS_MARKET=india`), India news/fundamental vendors, risk-free rate.
- `graph/*`: wires in the derivatives analyst.
- Analyst prompts: Indian market context.
- Bull/bear researchers, research manager and portfolio manager: `EVIDENCE_RULE` (use only reported numbers and show the arithmetic).
- `dataflows/y_finance.py`, `stockstats_utils.py`: NSE index-history fallback and an annual cash-flow fallback.
- `llm_clients/openai_client.py`: retries transient "overloaded" 429/5xx responses (`TRADINGAGENTS_UPSTREAM_RETRIES`).
- `cli/*`: Indian symbols and models.
- `tests/conftest.py`: hermetic environment.

## Using it on its own

```bash
cd packages/tradingagents
python -m pytest -q -p no:cacheprovider   # 783 tests, offline
tradingagents                             # interactive CLI; set TRADINGAGENTS_MARKET=india in the repo-root .env
```

## Updating from upstream

Diff a fresh upstream checkout against `be952b8`, then apply the relevant changes here and run the tests above plus
DalalSight tests (`python -m pytest` from the repository root).
