import { useState } from "react";
import { useApp } from "../context/AppContext";
import { useApi, useEvents } from "../lib/hooks";
import type { Snapshot } from "../lib/types";
import { EventsCard, LevelsCard, OptionsSnapshotCard, RegimeCard, SignalPanel, TechnicalCard } from "../components/analysis";
import CommentaryFeed from "../components/CommentaryFeed";
import { Help } from "../components/InfoTip";
import { SymbolPicker } from "../components/pickers";
import SignalSummary from "../components/SignalSummary";
import { LevelsSimple, MoodCard, WelcomeGuide } from "../components/SimpleCards";
import TradingChart from "../components/TradingChart";
import TradingViewPanel from "../components/TradingViewPanel";
import { Button, Card, ErrorNote, Select, Spinner } from "../components/ui";

const MAIN_TIMEFRAMES: [string, string][] = [
  ["5m", "5 min"],
  ["15m", "15 min"],
  ["1h", "1 hour"],
  ["1D", "1 day"],
];
const MORE_TIMEFRAMES: [string, string][] = [
  ["1m", "1 min"],
  ["3m", "3 min"],
  ["30m", "30 min"],
  ["4h", "4 hours"],
  ["1W", "1 week"],
];
const PLAN_LABELS = new Set(["BULLISH SETUP", "BEARISH SETUP", "HIGH-RISK SETUP"]);

export default function Dashboard() {
  const { symbol, timeframe, setTimeframe, status } = useApp();
  const [tradingViewOpen, setTradingViewOpen] = useState(false);
  const ready = Boolean(symbol && timeframe);
  const trading = Boolean(status?.market.is_trading);
  const analysis = useApi<Snapshot>(ready ? `/api/analysis/${symbol}?timeframe=${timeframe}` : null, { interval: trading ? 30_000 : 300_000 });

  useEvents(["market_update"], (message) => {
    const data = message.data as Snapshot;
    if (data?.signal && data.symbol === symbol && data.timeframe === timeframe) analysis.setData(data);
  });

  const snap = analysis.data && analysis.data.symbol === symbol && analysis.data.timeframe === timeframe ? analysis.data : null;
  const plan = snap && PLAN_LABELS.has(snap.signal.label) ? snap.signal.plan : null;
  const inMore = MORE_TIMEFRAMES.some(([tf]) => tf === timeframe);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-edge bg-panel px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-1.5 text-xs font-medium text-muted">
            Market <Help topic="markets" />
          </span>
          <SymbolPicker />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-1.5 text-xs font-medium text-muted">
            Candle size <Help topic="timeframe" />
          </span>
          <div className="inline-flex rounded border border-edge bg-bg p-0.5" role="group" aria-label="Candle size">
            {MAIN_TIMEFRAMES.map(([tf, label]) => (
              <button
                key={tf}
                type="button"
                aria-pressed={tf === timeframe}
                onClick={() => setTimeframe(tf)}
                className={`rounded px-2.5 py-1 text-xs ${tf === timeframe ? "bg-accent font-medium text-bg" : "text-muted hover:text-text"}`}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="w-28">
            <Select id="more-candle-sizes" aria-label="More candle sizes" value={inMore ? timeframe : ""} onChange={(event) => event.target.value && setTimeframe(event.target.value)} className="text-xs">
              <option value="">More…</option>
              {MORE_TIMEFRAMES.map(([tf, label]) => (
                <option key={tf} value={tf}>
                  {label}
                </option>
              ))}
            </Select>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {analysis.loading && <Spinner label="Updating" />}
          <Button onClick={analysis.reload}>↻ Refresh</Button>
        </div>
      </div>

      {symbol &&
        timeframe &&
        (tradingViewOpen ? (
          <TradingViewPanel symbol={symbol} timeframe={timeframe} onClose={() => setTradingViewOpen(false)} />
        ) : (
          <TradingChart symbol={symbol} timeframe={timeframe} plan={plan} levels={snap?.levels ?? null} isTrading={trading} onOpenTradingView={() => setTradingViewOpen(true)} />
        ))}

      <WelcomeGuide />
      <ErrorNote error={analysis.error} />

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="min-w-0">
          {snap ? (
            <SignalSummary snap={snap} />
          ) : (
            !analysis.error && (
              <Card title="Signal">
                <Spinner label="Checking the market" />
              </Card>
            )
          )}
        </div>
        {snap && (
          <div className="min-w-0 space-y-3">
            <LevelsSimple levels={snap.levels} price={snap.price} />
            <MoodCard regime={snap.regime} />
          </div>
        )}
      </div>

      {snap && (
        <details className="group rounded-lg border border-edge bg-panel">
          <summary className="flex items-center gap-2 px-3 py-2.5 text-sm">
            <span className="text-muted transition group-open:rotate-90">▸</span>
            Advanced details <span className="text-xs text-muted">(all numbers, for experienced traders)</span>
            <Help topic="advanced" />
          </summary>
          <div className="grid gap-3 border-t border-edge p-3 lg:grid-cols-2">
            <SignalPanel snap={snap} />
            <div className="space-y-3">
              <RegimeCard regime={snap.regime} />
              <OptionsSnapshotCard snap={snap} />
              <EventsCard events={snap.events} />
            </div>
            <LevelsCard levels={snap.levels} />
            <TechnicalCard technical={snap.technical} />
          </div>
        </details>
      )}

      <CommentaryFeed symbol={symbol} limit={10} title="Latest updates" info={<Help topic="updates" align="right" />} />
    </div>
  );
}
