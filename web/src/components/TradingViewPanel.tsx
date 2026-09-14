import { useEffect, useRef } from "react";
import { useApp } from "../context/AppContext";
import { Help } from "./InfoTip";
import { Spinner } from "./ui";

const WIDGET_SCRIPT = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";

/**
 * The symbol TradingView's free chart widget will draw, or null when it refuses. Checked 15 Sep 2026: NSE markets
 * (NIFTY, GIFT Nifty, NSE stocks) show "only available on TradingView"; BSE indices and BSE stock prices work on
 * daily, weekly and monthly candles. BSE tickers use "_" for special characters (M&M → BSE:M_M).
 */
function widgetSymbol(symbol: string, indices: Record<string, { tradingview: string }>): string | null {
  const index = indices[symbol];
  if (index) return index.tradingview.startsWith("BSE:") ? index.tradingview : null;
  return `BSE:${symbol.replace(/[^A-Z0-9]/g, "_")}`;
}

function Widget({ tvSymbol, interval, theme }: { tvSymbol: string; interval: string; theme: "dark" | "light" }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const target = document.createElement("div");
    target.className = "tradingview-widget-container__widget";
    target.style.height = "100%";
    target.style.width = "100%";
    const script = document.createElement("script");
    script.src = WIDGET_SCRIPT;
    script.type = "text/javascript";
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: tvSymbol,
      interval,
      timezone: "Asia/Kolkata",
      theme,
      backgroundColor: theme === "dark" ? "#000000" : "#ffffff",
      style: "1",
      locale: "en",
      allow_symbol_change: true,
      withdateranges: true,
      hide_side_toolbar: false,
      save_image: true,
      calendar: false,
      support_host: "https://www.tradingview.com",
    });
    element.replaceChildren(target, script);
    return () => element.replaceChildren();
  }, [tvSymbol, interval, theme]);
  return <div ref={box} className="tradingview-widget-container h-full w-full" />;
}

/** The real TradingView chart (free Advanced Chart widget), opened from the main chart's TradingView button. */
export default function TradingViewPanel({ symbol, timeframe, onClose }: { symbol: string; timeframe: string; onClose: () => void }) {
  const { config, settings, setSymbol } = useApp();
  const theme = settings?.theme === "light" ? "light" : "dark";
  const enabled = config?.public.tradingview_widget_enabled !== false;
  const tvSymbol = config ? widgetSymbol(symbol, config.indices) : null;
  const isIndex = Boolean(config?.indices[symbol]);
  const weekly = timeframe === "1W";
  const intraday = !weekly && timeframe !== "1D";
  const buttonClass = "rounded border border-edge px-3 py-1.5 text-sm hover:border-accent";
  const primaryClass = "rounded bg-accent px-3 py-1.5 text-sm font-medium text-bg hover:brightness-110";

  let body;
  if (!config) {
    body = (
      <div className="flex h-[460px] items-center justify-center">
        <Spinner label="Loading" />
      </div>
    );
  } else if (!enabled) {
    body = (
      <div className="flex h-[460px] flex-col items-center justify-center gap-3 p-6 text-center text-sm">
        <p>The TradingView chart is turned off on the server (TRADINGVIEW_WIDGET_ENABLED=false in .env).</p>
        <button type="button" onClick={onClose} className={primaryClass}>
          Back to chart
        </button>
      </div>
    );
  } else if (!tvSymbol) {
    body = (
      <div className="flex min-h-[460px] flex-col items-center justify-center gap-3 p-6 text-center text-sm">
        <p className="text-base font-semibold">TradingView doesn&apos;t allow {config.indices[symbol]?.name ?? symbol} here</p>
        <p className="max-w-lg text-muted">
          TradingView only lets other apps show BSE markets. NSE markets such as NIFTY and BANKNIFTY show &quot;This symbol is only available on TradingView&quot; inside
          another app, so they can&apos;t be shown here. The main DalalSight chart shows this market with BUY/SELL arrows and %.
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          <button type="button" onClick={onClose} className={primaryClass}>
            Back to chart
          </button>
          <button type="button" onClick={() => setSymbol("SENSEX")} className={buttonClass}>
            Show SENSEX in TradingView
          </button>
        </div>
      </div>
    );
  } else {
    body = (
      <div className="h-[460px] sm:h-[560px]">
        <Widget tvSymbol={tvSymbol} interval={weekly ? "W" : "D"} theme={theme} />
      </div>
    );
  }

  return (
    <section className="min-w-0 overflow-hidden rounded-lg border border-edge bg-panel" aria-label="TradingView chart">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-edge px-3 py-2 text-sm">
        <button type="button" onClick={onClose} className={buttonClass}>
          ← Back to chart
        </button>
        <span className="font-semibold">TradingView{tvSymbol ? ` · ${tvSymbol}` : ""}</span>
        {tvSymbol && <span className="text-xs text-muted">{weekly ? "Weekly" : "Daily"} candles</span>}
        <span className="ml-auto">
          <Help topic="chartViews" align="right" />
        </span>
      </div>
      {tvSymbol && enabled && (
        <div className="space-y-0.5 border-b border-edge px-3 py-1.5 text-xs text-muted">
          {intraday && <p>TradingView gives other apps BSE prices on daily or weekly candles only.</p>}
          {!isIndex && <p>Prices are from BSE and can differ slightly from NSE. If this stock isn&apos;t listed on BSE, TradingView says the symbol doesn&apos;t exist.</p>}
          <p>TradingView doesn&apos;t let other apps draw on its chart, so BUY/SELL arrows and % are on the main chart and in the signal box.</p>
        </div>
      )}
      {body}
      <div className="border-t border-edge px-3 py-1.5 text-right text-[11px] text-muted">
        <a href="https://www.tradingview.com/" rel="noopener nofollow" target="_blank" className="hover:text-text">
          Chart by TradingView
        </a>
      </div>
    </section>
  );
}
