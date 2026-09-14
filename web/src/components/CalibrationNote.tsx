import { Link } from "react-router-dom";
import { istTime, num } from "../lib/format";
import { useApi } from "../lib/hooks";
import type { Calibration, CalibrationBucket } from "../lib/types";
import { TEXT_TONES, type Tone } from "../lib/tones";

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

/** How the stated bullish % held up in the newest backtest of this symbol and timeframe, next to the live signal. */
export default function CalibrationNote({ symbol, timeframe, bullish }: { symbol: string; timeframe: string; bullish: number }) {
  const latest = useApi<LatestCalibration>(`/api/calibration/${symbol}?timeframe=${timeframe}`, { interval: 600_000 });
  const data = latest.data;
  if (!data) return null;
  if (!data.available) {
    return (
      <div className="mt-2 text-[11px] text-muted">
        Track record: no backtest yet for {symbol} {timeframe}.{" "}
        <Link to="/signals" className="text-accent hover:underline">
          Run one
        </Link>{" "}
        to see how often this bullish % came true.
      </div>
    );
  }
  const bucket = bucketFor(data.by_bullish_pct, bullish);
  const resolved = bucket ? bucket.up_first + bucket.down_first : 0;
  let tone: Tone = "muted";
  let verdict = `too few resolved bars (${resolved}) to judge`;
  if (bucket && bucket.observed_up_pct !== null && bucket.stated_bullish_pct !== null && resolved >= MIN_RESOLVED) {
    const gap = Math.abs(bucket.observed_up_pct - bucket.stated_bullish_pct);
    tone = gap <= 5 ? "bull" : gap <= 10 ? "warn" : "bear";
    verdict =
      gap <= 5
        ? "close to the stated %"
        : gap <= 10
          ? `${num(gap, 0)} points off the stated %`
          : `${num(gap, 0)} points off: the stated % has not been reliable here`;
  }
  return (
    <div className="mt-2 rounded border border-edge bg-bg/40 p-2 text-[11px] leading-snug">
      <span className="text-muted">Track record (backtest #{data.backtest_id}, {istTime(data.period.start, { date: true })} → {istTime(data.period.end, { date: true })}): </span>
      {bucket ? (
        <>
          when the engine stated {bucket.bucket}% bullish, price touched +{num(data.touch_atr, 0)} ATR before −{num(data.touch_atr, 0)} ATR in{" "}
          <span className={`font-mono ${TEXT_TONES[tone]}`}>{bucket.observed_up_pct === null ? "—" : `${num(bucket.observed_up_pct, 0)}%`}</span> of {resolved} bars
          {" · "}
          <span className={TEXT_TONES[tone]}>{verdict}</span>.
        </>
      ) : (
        "no bucket matches this reading."
      )}
      {data.mean_abs_gap_pts !== null && <span className="text-muted"> Mean gap across buckets {num(data.mean_abs_gap_pts, 1)} points.</span>}
    </div>
  );
}
