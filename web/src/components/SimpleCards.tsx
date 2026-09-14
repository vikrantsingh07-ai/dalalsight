import { num, pct } from "../lib/format";
import type { HelpTopic } from "../lib/help";
import { useLocalState } from "../lib/hooks";
import type { Levels, Regime } from "../lib/types";
import { TEXT_TONES, type Tone } from "../lib/tones";
import { Help } from "./InfoTip";
import { Button, Card } from "./ui";

export function WelcomeGuide() {
  const [done, setDone] = useLocalState("cc_welcome_done", false);
  if (done) return null;
  return (
    <section className="rounded-lg border border-info/40 bg-info/10 p-3" aria-labelledby="welcome-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-3xl">
          <h2 id="welcome-title" className="font-display text-base font-semibold">
            New here? Use DalalSight in 3 steps
          </h2>
          <ol className="mt-1.5 list-decimal space-y-1 pl-5 text-sm">
            <li>
              <strong>Pick a market</strong> such as NIFTY, and a <strong>candle size</strong>: 5 min for today's moves, 1 day for the bigger picture.
            </li>
            <li>
              <strong>Read the signal box</strong>: BUY, SELL or WAIT, with the reasons in plain words.
            </li>
            <li>
              <strong>Look at the chart</strong>: green ▲ and red ▼ arrows show where signals appeared; dotted lines are the price floor and ceiling.
            </li>
          </ol>
          <p className="mt-1.5 text-xs text-muted">Tap any small (i) button to learn what a word means. DalalSight is for learning and research and never places real orders.</p>
        </div>
        <Button variant="primary" onClick={() => setDone(true)}>
          Got it
        </Button>
      </div>
    </section>
  );
}

function LevelRow({ label, topic, price, now, tone, note }: { label: string; topic: HelpTopic; price: number | undefined; now: number; tone: Tone; note?: string }) {
  const away = price ? ((price - now) / now) * 100 : null;
  return (
    <div className="rounded border border-edge bg-bg/40 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs text-muted">
          {label} <Help topic={topic} />
        </span>
        <span className={`font-mono text-base ${TEXT_TONES[tone]}`}>{num(price)}</span>
      </div>
      <div className="mt-0.5 flex justify-between gap-2 text-[11px] text-muted">
        <span className="truncate">{note ?? "none found nearby"}</span>
        {away !== null && <span className="shrink-0 font-mono">{pct(away)} from now</span>}
      </div>
    </div>
  );
}

export function LevelsSimple({ levels, price }: { levels: Levels; price: number }) {
  return (
    <Card title="Price floor and ceiling" info={<Help topic="support" />}>
      <div className="grid gap-2">
        <LevelRow label="Ceiling (resistance)" topic="resistance" price={levels.nearest_resistance?.price} now={price} tone="bear" note={levels.nearest_resistance?.label} />
        <div className="flex items-center justify-between rounded px-3 text-xs text-muted">
          <span>Price now</span>
          <span className="font-mono text-text">{num(price)}</span>
        </div>
        <LevelRow label="Floor (support)" topic="support" price={levels.nearest_support?.price} now={price} tone="bull" note={levels.nearest_support?.label} />
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-muted">
        A close above <span className="font-mono text-text">{num(levels.breakout_level)}</span> or below <span className="font-mono text-text">{num(levels.breakdown_level)}</span> often starts a bigger move{" "}
        <Help topic="levelsBreak" align="right" />
      </p>
    </Card>
  );
}

const MOODS: Record<string, { title: string; text: string }> = {
  STRONG_BULLISH_TREND: { title: "Strong uptrend", text: "Prices have been rising steadily." },
  WEAK_BULLISH_TREND: { title: "Mild uptrend", text: "Prices are drifting up, without much force." },
  STRONG_BEARISH_TREND: { title: "Strong downtrend", text: "Prices have been falling steadily." },
  WEAK_BEARISH_TREND: { title: "Mild downtrend", text: "Prices are drifting down, without much force." },
  RANGE_BOUND: { title: "Sideways", text: "Prices are moving between a floor and a ceiling. Breakouts often fail in this mood." },
  HIGH_VOLATILITY: { title: "Very jumpy", text: "Big swings in both directions. Risk is higher than usual." },
  LOW_VOLATILITY: { title: "Very quiet", text: "Small moves. A bigger move often follows a quiet spell." },
  BREAKOUT: { title: "Breakout", text: "Price just left its recent range with bigger moves." },
  TRANSITION: { title: "Changing", text: "No clear pattern yet; the direction may be turning." },
  INSUFFICIENT_DATA: { title: "Not enough data", text: "There are too few candles to judge the mood." },
};

const MOVE_SIZE: Record<string, string> = { high: "bigger than usual", normal: "normal", low: "smaller than usual", unknown: "not known yet" };

export function MoodCard({ regime }: { regime: Regime }) {
  const mood = MOODS[regime.code] ?? { title: regime.label, text: "" };
  const title = regime.code === "BREAKOUT" ? `Breakout ${regime.direction > 0 ? "upward" : "downward"}` : mood.title;
  const tone: Tone = regime.direction > 0 ? "bull" : regime.direction < 0 ? "bear" : regime.code === "HIGH_VOLATILITY" ? "warn" : "info";
  return (
    <Card title="Market mood" info={<Help topic="mood" />}>
      <div className={`font-display text-lg font-semibold ${TEXT_TONES[tone]}`}>{title}</div>
      <p className="mt-1 text-xs leading-relaxed text-text">{mood.text}</p>
      <p className="mt-2 text-[11px] text-muted">Size of moves: {MOVE_SIZE[regime.volatility] ?? regime.volatility}</p>
    </Card>
  );
}
