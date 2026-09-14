import type { ConfigPayload } from "./types";

const INTERVALS: Record<string, string> = { "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1D": "D", "1W": "W" };

/** Continuous front-month index futures on TradingView; they carry the volume that spot indices lack. */
export const INDEX_FUTURES: Record<string, string> = {
  NIFTY: "NSE:NIFTY1!",
  BANKNIFTY: "NSE:BANKNIFTY1!",
  FINNIFTY: "NSE:FINNIFTY1!",
  MIDCPNIFTY: "NSE:MIDCPNIFTY1!",
};

export function tvSymbolFor(symbol: string, config: ConfigPayload | null): string {
  return config?.indices[symbol]?.tradingview ?? `NSE:${symbol}`;
}

/** Official TradingView chart link; NSE/BSE data is only shown inside TradingView, not in embeds. */
export function tvChartUrl(tvSymbol: string, timeframe?: string): string {
  const params = new URLSearchParams({ symbol: tvSymbol });
  if (timeframe && INTERVALS[timeframe]) params.set("interval", INTERVALS[timeframe]);
  return `https://www.tradingview.com/chart/?${params.toString()}`;
}
