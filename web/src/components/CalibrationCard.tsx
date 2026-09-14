import { num } from "../lib/format";
import { plainLabel } from "../lib/plain";
import type { Calibration, CalibrationBucket } from "../lib/types";
import { TEXT_TONES, toneForLabel, toneForNumber, type Tone } from "../lib/tones";
import { Card, Empty, Pill, Table } from "./ui";

const MIN_RESOLVED = 30;

function percent(value: number | null): string {
  return value === null ? "—" : `${num(value, 1)}%`;
}

/** Colour the observed rate by how far it is from what the engine stated; thin buckets stay neutral. */
function gapTone(bucket: CalibrationBucket): Tone {
  if (bucket.observed_up_pct === null || bucket.stated_bullish_pct === null || bucket.up_first + bucket.down_first < MIN_RESOLVED) return "muted";
  const gap = Math.abs(bucket.observed_up_pct - bucket.stated_bullish_pct);
  return gap <= 5 ? "bull" : gap <= 10 ? "warn" : "bear";
}

function Touches({ bucket }: { bucket: CalibrationBucket }) {
  return (
    <span className="font-mono text-muted">
      {bucket.up_first} / {bucket.down_first} / {bucket.neither + bucket.ambiguous}
    </span>
  );
}

export default function CalibrationCard({ calibration }: { calibration: Calibration }) {
  const c = calibration;
  return (
    <Card title={`Calibration · stated vs observed · ${c.samples} bars`}>
      {c.samples === 0 ? (
        <Empty>No bars to evaluate.</Empty>
      ) : (
        <div className="space-y-3">
          <p className="text-[11px] text-muted">{c.method}</p>
          <div className="text-xs">
            Mean gap between stated bullish % and observed up-first %:{" "}
            <span className="font-mono">{c.mean_abs_gap_pts === null ? `— (no bucket has ${MIN_RESOLVED}+ resolved bars)` : `${num(c.mean_abs_gap_pts, 1)} points`}</span>
          </div>

          <Table>
            <thead>
              <tr>
                <th>Stated bullish %</th>
                <th>Bars</th>
                <th>Avg stated</th>
                <th>Observed up-first</th>
                <th>Up / down / neither</th>
                <th>Avg move (ATR)</th>
              </tr>
            </thead>
            <tbody>
              {c.by_bullish_pct.map((b) => (
                <tr key={b.bucket}>
                  <td className="font-mono">{b.bucket}</td>
                  <td className="font-mono">{b.samples}</td>
                  <td className="font-mono">{percent(b.stated_bullish_pct)}</td>
                  <td className={`font-mono ${TEXT_TONES[gapTone(b)]}`}>{percent(b.observed_up_pct)}</td>
                  <td>
                    <Touches bucket={b} />
                  </td>
                  <td className={`font-mono ${TEXT_TONES[toneForNumber(b.avg_forward_atr)]}`}>{num(b.avg_forward_atr, 2)}</td>
                </tr>
              ))}
            </tbody>
          </Table>

          <div className="grid gap-3 lg:grid-cols-2">
            <Table>
              <thead>
                <tr>
                  <th>Label</th>
                  <th>Bars</th>
                  <th>Hit % (its direction)</th>
                  <th>Avg move in direction</th>
                </tr>
              </thead>
              <tbody>
                {c.by_label.map((b) => (
                  <tr key={b.bucket}>
                    <td>
                      <Pill tone={toneForLabel(b.bucket)}>{plainLabel(b.bucket)}</Pill>
                    </td>
                    <td className="font-mono">{b.samples}</td>
                    <td className="font-mono">{b.directional_samples ? percent(b.hit_pct) : "no direction"}</td>
                    <td className={`font-mono ${TEXT_TONES[toneForNumber(b.avg_forward_atr_in_direction)]}`}>{num(b.avg_forward_atr_in_direction, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Table>
              <thead>
                <tr>
                  <th>Model confidence</th>
                  <th>Bars with a direction</th>
                  <th>Hit %</th>
                  <th>Avg move in direction</th>
                </tr>
              </thead>
              <tbody>
                {c.by_confidence.map((b) => (
                  <tr key={b.bucket}>
                    <td className="font-mono">{b.bucket}</td>
                    <td className="font-mono">{b.samples}</td>
                    <td className="font-mono">{percent(b.hit_pct)}</td>
                    <td className={`font-mono ${TEXT_TONES[toneForNumber(b.avg_forward_atr_in_direction)]}`}>{num(b.avg_forward_atr_in_direction, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
          <p className="text-[11px] text-muted">{c.note}</p>
        </div>
      )}
    </Card>
  );
}
