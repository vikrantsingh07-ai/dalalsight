import { useApp } from "../context/AppContext";
import { useApi, useEvents, useLocalState } from "../lib/hooks";
import type { ChartData, Snapshot } from "../lib/types";
import { EventsCard, LevelsCard, OptionsSnapshotCard, ProvenanceLine, RegimeCard, SignalPanel, TechnicalCard } from "../components/analysis";
import CommentaryFeed from "../components/CommentaryFeed";
import { SymbolPicker, TimeframePicker } from "../components/pickers";
import PriceChart, { type Overlays } from "../components/PriceChart";
import TradingViewWidget from "../components/TradingViewWidget";
import { Button, Card, Checkbox, ErrorNote, Pill, Spinner, Tabs, UnavailableNote } from "../components/ui";

const DEFAULT_OVERLAYS: Overlays = { ema: true, vwap: true, bb: false, supertrend: false, levels: true, plan: true, rsi: true, macd: false };
const OVERLAY_LABELS: Record<keyof Overlays, string> = { ema: "EMA", vwap: "VWAP", bb: "Bollinger", supertrend: "Supertrend", levels: "S/R levels", plan: "Trade plan", rsi: "RSI", macd: "MACD" };

export default function Dashboard() {
  const { symbol, timeframe, setTimeframe, config, settings, status } = useApp();
  const [view, setView] = useLocalState<"engine" | "tradingview">("cc_chart_view", "engine");
  const [overlays, setOverlays] = useLocalState<Overlays>("cc_overlays", DEFAULT_OVERLAYS);
  const ready = Boolean(symbol && timeframe);
  const chart = useApi<ChartData>(ready ? `/api/chart/${symbol}?timeframe=${timeframe}&bars=400` : null, { interval: status?.market.is_trading ? 60_000 : 300_000 });
  const analysis = useApi<Snapshot>(ready ? `/api/analysis/${symbol}?timeframe=${timeframe}` : null, { interval: status?.market.is_trading ? 30_000 : 300_000 });

  useEvents(["market_update"], (message) => {
    const data = message.data as Snapshot;
    if (data?.signal && data.symbol === symbol && data.timeframe === timeframe) analysis.setData(data);
  });

  const snap = analysis.data && analysis.data.symbol === symbol && analysis.data.timeframe === timeframe ? analysis.data : null;
  const chartData = chart.data && chart.data.symbol === symbol && chart.data.timeframe === timeframe ? chart.data : null;
  const tvSymbol = snap?.meta.tradingview_symbol ?? config?.indices[symbol]?.tradingview ?? `NSE:${symbol}`;
  const tvEnabled = config?.public.tradingview_widget_enabled !== false;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <SymbolPicker />
        <TimeframePicker value={timeframe} onChange={setTimeframe} />
        <Tabs
          tabs={[
            { id: "engine", label: "Engine chart" },
            { id: "tradingview", label: "TradingView" },
          ]}
          value={view}
          onChange={setView}
        />
        <Button
          onClick={() => {
            chart.reload();
            analysis.reload();
          }}
        >
          Refresh
        </Button>
        {(chart.loading || analysis.loading) && <Spinner label="Updating" />}
        {snap?.market && !snap.market.is_trading && <Pill tone="muted">Market closed · showing last session data</Pill>}
      </div>

      <div className="grid gap-3 2xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-3">
          <Card
            title={
              <span>
                <span className="font-mono">{symbol}</span> · {timeframe} {snap?.meta.name ? <span className="font-body text-xs font-normal text-muted">{snap.meta.name}</span> : null}
              </span>
            }
            actions={
              view === "engine" ? (
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  {(Object.keys(OVERLAY_LABELS) as (keyof Overlays)[]).map((key) => (
                    <Checkbox key={key} label={OVERLAY_LABELS[key]} checked={overlays[key]} onChange={(value) => setOverlays({ ...overlays, [key]: value })} />
                  ))}
                </div>
              ) : undefined
            }
            bodyClass="p-0"
          >
            {view === "engine" ? (
              <div className="p-2">
                <ErrorNote error={chart.error} />
                {chartData ? <PriceChart data={chartData} overlays={overlays} plan={snap?.signal.plan} /> : !chart.error && <div className="flex h-[480px] items-center justify-center"><Spinner label="Loading chart" /></div>}
                {chartData && (
                  <div className="px-1 pt-2">
                    <ProvenanceLine provenance={chartData.provenance} />
                  </div>
                )}
              </div>
            ) : tvEnabled ? (
              <div>
                <div className="h-[560px]">
                  <TradingViewWidget symbol={tvSymbol} timeframe={timeframe} theme={settings?.theme ?? "dark"} />
                </div>
                <p className="border-t border-edge px-3 py-2 text-[11px] text-muted">
                  Official TradingView Advanced Chart widget showing TradingView&apos;s own data for {tvSymbol}. It is display-only: signals, levels and commentary use the backend market-data provider. Some NSE symbols may be restricted on the free widget.
                </p>
              </div>
            ) : (
              <div className="p-3">
                <UnavailableNote info={{ what: "TradingView widget", reason: "disabled", requirement: "TRADINGVIEW_WIDGET_ENABLED=true" }} />
              </div>
            )}
          </Card>

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
          {snap ? <SignalPanel snap={snap} /> : !analysis.error && <Card title="Signal confidence engine"><Spinner label="Analysing" /></Card>}
          {snap && <RegimeCard regime={snap.regime} />}
          {snap && <OptionsSnapshotCard snap={snap} />}
          <CommentaryFeed symbol={symbol} limit={20} />
        </div>
      </div>
    </div>
  );
}
