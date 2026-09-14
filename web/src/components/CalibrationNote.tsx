import { Link } from "react-router-dom";
import { MIN_RESOLVED, pastRate, useCalibration, type LatestCalibration } from "../lib/calibration";
import { istTime, num } from "../lib/format";
import { TEXT_TONES, type Tone } from "../lib/tones";
import { Help } from "./InfoTip";

/** In plain words: how often readings like the current one moved the signal's way in the newest backtest. */
export default function CalibrationNote({
  symbol,
  timeframe,
  bullish,
  direction = 0,
  latest,
}: {
  symbol: string;
  timeframe: string;
  bullish: number;
  direction?: number;
  /** Already-fetched calibration; when left out the note fetches it itself. */
  latest?: LatestCalibration | null;
}) {
  const fetched = useCalibration(latest === undefined ? symbol : null, timeframe);
  const data = latest === undefined ? fetched.data : latest;
  if (!data) return null;
  if (!data.available) {
    return (
      <div className="mt-3 flex flex-wrap items-center gap-1.5 rounded border border-edge bg-bg/40 p-2 text-[12px] text-muted">
        Past check: not tested yet for {symbol} {timeframe}.
        <Link to="/signals" className="text-info hover:underline">
          Run a test
        </Link>
        <Help topic="trackRecord" align="right" />
      </div>
    );
  }
  const past = pastRate(data, bullish, direction);
  const down = direction < 0;
  const claimed = down ? 100 - bullish : bullish;
  let tone: Tone = "muted";
  let verdict = "too few past cases to judge";
  if (past && past.resolved >= MIN_RESOLVED) {
    const gap = Math.abs(past.rate - claimed);
    tone = gap <= 5 ? "bull" : gap <= 10 ? "warn" : "bear";
    verdict = gap <= 5 ? "close to what it claims" : gap <= 10 ? "somewhat off" : Math.abs(past.rate - 50) <= 7 ? "about a coin flip, so don't rely on it" : "not reliable here";
  }
  return (
    <div className="mt-3 rounded border border-edge bg-bg/40 p-2 text-[12px] leading-snug">
      <div className="mb-0.5 flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted">
        Past check <Help topic="trackRecord" align="right" />
      </div>
      {past ? (
        <>
          In a test from {istTime(data.period.start, { date: true })} to {istTime(data.period.end, { date: true })}, readings like this one went {down ? "down" : "up"} first{" "}
          <span className={`font-mono ${TEXT_TONES[tone]}`}>{num(past.rate, 0)}%</span> of {past.resolved} times: <span className={TEXT_TONES[tone]}>{verdict}</span>.
        </>
      ) : (
        <span className="text-muted">No past cases match this reading.</span>
      )}
    </div>
  );
}
