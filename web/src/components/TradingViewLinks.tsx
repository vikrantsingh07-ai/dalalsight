import { useApp } from "../context/AppContext";
import { INDEX_FUTURES, tvChartUrl, tvSymbolFor } from "../lib/tradingview";
import { Card, UnavailableNote } from "./ui";

const LINK = "inline-flex items-center justify-center gap-1.5 rounded border px-3 py-2 text-sm font-medium transition";

export default function TradingViewLinks({ symbol, timeframe }: { symbol: string; timeframe: string }) {
  const { config } = useApp();
  if (config?.public.tradingview_widget_enabled === false) {
    return (
      <Card title="Chart in TradingView">
        <UnavailableNote info={{ what: "TradingView links", reason: "disabled", requirement: "TRADINGVIEW_WIDGET_ENABLED=true" }} />
      </Card>
    );
  }
  const spot = tvSymbolFor(symbol, config);
  const futures = INDEX_FUTURES[symbol];
  return (
    <Card title="Chart in TradingView">
      <div className="flex flex-wrap items-center gap-2">
        <a className={`${LINK} border-accent bg-accent text-bg hover:brightness-110`} href={tvChartUrl(spot, timeframe)} target="_blank" rel="noopener noreferrer">
          Open {spot} · {timeframe} in TradingView ↗
        </a>
        {futures && (
          <a className={`${LINK} border-edge bg-panel-2 text-text hover:border-muted`} href={tvChartUrl(futures, timeframe)} target="_blank" rel="noopener noreferrer">
            Futures {futures} ↗
          </a>
        )}
      </div>
      <p className="mt-2 text-[11px] leading-snug text-muted">
        TradingView does not allow NSE/BSE charts inside embedded widgets (exchange data licensing: they show &quot;This symbol is only available on TradingView&quot;), so charts open in TradingView itself: the web app, or your desktop app if it handles TradingView links.
        {futures ? " Use the futures chart for the indicator's volume and VWAP components; the spot index has no volume." : ""}
      </p>
    </Card>
  );
}
