import { useApi } from "./hooks";
import type { Calibration, CalibrationBucket } from "./types";

/** Buckets with fewer resolved past cases than this are too noisy to quote as a percentage. */
export const MIN_RESOLVED = 30;

export type LatestCalibration =
  | ({ available: true; symbol: string; timeframe: string; backtest_id: number; created_at: string; period: { start: string; end: string; bars: number } } & Calibration)
  | { available: false; symbol: string; timeframe: string; reason: string };

export interface PastRate {
  /** % of resolved past cases that moved the signal's way first (+1 ATR before −1 ATR). */
  rate: number;
  resolved: number;
  enough: boolean;
}

export function bucketFor(buckets: CalibrationBucket[], bullish: number): CalibrationBucket | undefined {
  return buckets.find((bucket) => {
    const [low, high] = bucket.bucket.split("–").map(Number);
    return bullish >= low && (bullish < high || high >= 100);
  });
}

/**
 * The "past check" for a reading: in the newest backtest of this market and candle size, how often readings in the same
 * bullish-% bucket went the signal's way first. It is a measured frequency, not a promise; the engine's own bullish %
 * is not calibrated (14 Sep 2026 backtests), so it must never be shown as a probability.
 */
export function pastRate(latest: LatestCalibration | null | undefined, bullish: number, direction: number): PastRate | null {
  if (!latest || !latest.available) return null;
  const bucket = bucketFor(latest.by_bullish_pct, bullish);
  if (!bucket || bucket.observed_up_pct === null) return null;
  const resolved = bucket.up_first + bucket.down_first;
  const rate = direction < 0 ? 100 - bucket.observed_up_pct : bucket.observed_up_pct;
  return { rate, resolved, enough: resolved >= MIN_RESOLVED };
}

export function useCalibration(symbol: string | null, timeframe: string) {
  return useApi<LatestCalibration>(symbol ? `/api/calibration/${encodeURIComponent(symbol)}?timeframe=${timeframe}` : null, { interval: 600_000 });
}
