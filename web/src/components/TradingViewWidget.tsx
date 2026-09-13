import { useEffect, useRef } from "react";

const INTERVALS: Record<string, string> = { "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1D": "D", "1W": "W" };

/**
 * Official TradingView Advanced Chart embed widget (https://www.tradingview.com/widget/advanced-chart/).
 * It renders TradingView's own data feed; the backend analysis never reads from it.
 */
export default function TradingViewWidget({ symbol, timeframe, theme }: { symbol: string; timeframe: string; theme: "dark" | "light" }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    element.innerHTML = "";
    const widget = document.createElement("div");
    widget.className = "tradingview-widget-container__widget";
    widget.style.height = "100%";
    widget.style.width = "100%";
    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.type = "text/javascript";
    script.async = true;
    script.textContent = JSON.stringify({
      autosize: true,
      symbol,
      interval: INTERVALS[timeframe] ?? "5",
      timezone: "Asia/Kolkata",
      theme,
      style: "1",
      locale: "en",
      allow_symbol_change: true,
      save_image: false,
      calendar: false,
      support_host: "https://www.tradingview.com",
    });
    element.appendChild(widget);
    element.appendChild(script);
    return () => {
      element.innerHTML = "";
    };
  }, [symbol, timeframe, theme]);

  return <div ref={host} className="tradingview-widget-container h-full w-full" />;
}
