import { useApp } from "../context/AppContext";
import { useApi, useEvents } from "../lib/hooks";
import type { Snapshot } from "../lib/types";
import { EventsCard, LevelsCard, OptionsSnapshotCard, RegimeCard, SignalPanel, TechnicalCard } from "../components/analysis";
import CommentaryFeed from "../components/CommentaryFeed";
import { SymbolPicker, TimeframePicker } from "../components/pickers";
import PineScriptCard from "../components/PineScriptCard";
import TradingViewLinks from "../components/TradingViewLinks";
import { Button, Card, ErrorNote, Pill, Spinner } from "../components/ui";

export default function Dashboard() {
  const { symbol, timeframe, setTimeframe, status } = useApp();
  const ready = Boolean(symbol && timeframe);
  const analysis = useApi<Snapshot>(ready ? `/api/analysis/${symbol}?timeframe=${timeframe}` : null, { interval: status?.market.is_trading ? 30_000 : 300_000 });

  useEvents(["market_update"], (message) => {
    const data = message.data as Snapshot;
    if (data?.signal && data.symbol === symbol && data.timeframe === timeframe) analysis.setData(data);
  });

  const snap = analysis.data && analysis.data.symbol === symbol && analysis.data.timeframe === timeframe ? analysis.data : null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <SymbolPicker />
        <TimeframePicker value={timeframe} onChange={setTimeframe} />
        <Button onClick={analysis.reload}>Refresh analysis</Button>
        {analysis.loading && <Spinner label="Updating" />}
        {snap?.market && !snap.market.is_trading && <Pill tone="muted">Market closed · showing last session data</Pill>}
      </div>

      <div className="grid gap-3 2xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-3">
          {symbol && timeframe && <TradingViewLinks symbol={symbol} timeframe={timeframe} />}
          <PineScriptCard />

          <ErrorNote error={analysis.error} />
          {snap && (
            <div className="grid gap-3 lg:grid-cols-2">
              <LevelsCard levels={snap.levels} />
              <div className="space-y-3">
                <EventsCard events={snap.events} />
                <TechnicalCard technical={snap.technical} />
              </div>
            </div>
          )}
        </div>

        <div className="min-w-0 space-y-3">
          {snap ? (
            <SignalPanel snap={snap} />
          ) : (
            !analysis.error && (
              <Card title="Signal confidence engine">
                <Spinner label="Analysing" />
              </Card>
            )
          )}
          {snap && <RegimeCard regime={snap.regime} />}
          {snap && <OptionsSnapshotCard snap={snap} />}
          <CommentaryFeed symbol={symbol} limit={20} />
        </div>
      </div>
    </div>
  );
}
