import { Link } from "react-router-dom";
import { istTime, num } from "../lib/format";
import { useApi } from "../lib/hooks";
import type { Calibration, CalibrationBucket } from "../lib/types";
import { TEXT_TONES, type Tone } from "../lib/tones";
import { Help } from "./InfoTip";

const MIN_RESOLVED = 30;

type LatestCalibration =
  | ({ available: true; backtest_id: number; created_at: string; period: { start: string; end: string; bars: number } } & Calibration)
  | { available: false; reason: string };

function bucketFor(buckets: CalibrationBucket[], bullish: number): CalibrationBucket | undefined {
  return buckets.find((bucket) => {
    const [low, high] = bucket.bucket.split("–").map(Number);
    return bullish >= low && (bullish < high || high >= 100);
  });
}

/** In plain words: how often readings like the current one moved the signal's way in the newest backtest. */
export default function CalibrationNote({ symbol, timeframe, bullish, direction = 0 }: { symbol: string; timeframe: string; bullish: number; direction?: number }) {
  const latest = useApi<LatestCalibration>(`/api/calibration/${symbol}?timeframe=${timeframe}`, { interval: 600_000 });
  const data = latest.data;
  if (!data) return null;
  if (!data.available) {
    return (
      <div className="mt-3 flex flex-wrap items-center gap-1.5 rounded border border-edge bg-bg/40 p-2 text-[12px] text-muted">
        Past check: not tested yet for {symbol} {timeframe}.
        <Link to="/signals" className="text-accent hover:underline">
          Run a test
        </Link>
        <Help topic="trackRecord" align="right" />
      </div>
    );
  }
  const bucket = bucketFor(data.by_bullish_pct, bullish);
  const resolved = bucket ? bucket.up_first + bucket.down_first : 0;
  const down = direction < 0;
  const upRate = bucket?.observed_up_pct ?? null;
  const rate = upRate === null ? null : down ? 100 - upRate : upRate;
  const claimed = down ? 100 - bullish : bullish;
  let tone: Tone = "muted";
  let verdict = "too few past cases to judge";
  if (rate !== null && resolved >= MIN_RESOLVED) {
    const gap = Math.abs(rate - claimed);
    tone = gap <= 5 ? "bull" : gap <= 10 ? "warn" : "bear";
    verdict = gap <= 5 ? "close to what it claims" : gap <= 10 ? "somewhat off" : Math.abs(rate - 50) <= 7 ? "about a coin flip, so don't rely on it" : "not reliable here";
  }
  return (
    <div className="mt-3 rounded border border-edge bg-bg/40 p-2 text-[12px] leading-snug">
      <div className="mb-0.5 flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted">
        Past check <Help topic="trackRecord" align="right" />
      </div>
      {bucket && rate !== null ? (
        <>
          In a test from {istTime(data.period.start, { date: true })} to {istTime(data.period.end, { date: true })}, readings like this one went {down ? "down" : "up"} first{" "}
          <span className={`font-mono ${TEXT_TONES[tone]}`}>{num(rate, 0)}%</span> of {resolved} times: <span className={TEXT_TONES[tone]}>{verdict}</span>.
        </>
      ) : (
        <span className="text-muted">No past cases match this reading.</span>
      )}
    </div>
  );
}
