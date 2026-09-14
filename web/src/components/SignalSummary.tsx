import { istTime, num, pct, signed } from "../lib/format";
import type { HelpTopic } from "../lib/help";
import { isUnavailable, type Signal, type Snapshot } from "../lib/types";
import { TEXT_TONES, toneForNumber, type Tone } from "../lib/tones";
import CalibrationNote from "./CalibrationNote";
import { Help } from "./InfoTip";
import { TIMEFRAME_LABELS } from "../lib/timeframes";
import { Card, Meter } from "./ui";

const PLAN_LABELS = new Set(["BULLISH SETUP", "BEARISH SETUP", "HIGH-RISK SETUP"]);

const BOX: Record<Tone, string> = {
  bull: "border-bull/50 bg-bull/10 text-bull",
  bear: "border-bear/50 bg-bear/10 text-bear",
  warn: "border-warn/50 bg-warn/10 text-warn",
  info: "border-info/50 bg-info/10 text-info",
  muted: "border-edge bg-bg/50 text-text",
  accent: "border-accent/50 bg-accent/10 text-accent",
};

// What each engine check means, in plain words: [pointing up, pointing down]
const PHRASES: Record<string, [string, string]> = {
  trend: ["The bigger trend is up", "The bigger trend is down"],
  momentum: ["Buying momentum is building", "Selling momentum is building"],
  volume: ["Trading volume supports the rise", "Trading volume supports the fall"],
  ema_structure: ["The short-term average is above the long-term one", "The short-term average is below the long-term one"],
  vwap: ["Price is above today's average price (VWAP)", "Price is below today's average price (VWAP)"],
  market_structure: ["The price pattern looks strong (higher lows or a floor close by)", "The price pattern looks weak (lower highs or a ceiling close by)"],
  volatility: ["Bigger moves are happening on the way up", "Bigger moves are happening on the way down"],
  options: ["Options traders are positioned for a rise", "Options traders are positioned for a fall"],
};

const CHECK_NAMES: Record<string, string> = {
  trend: "trend",
  momentum: "momentum",
  volume: "volume",
  ema_structure: "averages",
  vwap: "VWAP",
  market_structure: "price pattern",
  volatility: "volatility",
  options: "options",
};

function leaningUp(signal: Signal): boolean {
  return signal.direction ? signal.direction > 0 : signal.bullish_pct >= 50;
}

function verdict(signal: Signal): { title: string; text: string; tone: Tone; icon: string } {
  const up = leaningUp(signal);
  switch (signal.label) {
    case "BULLISH SETUP":
      return { title: "BUY setup", text: "Most checks point up. The plan below shows where it starts, where it is proven wrong, and where it may go.", tone: "bull", icon: "▲" };
    case "BEARISH SETUP":
      return { title: "SELL setup", text: "Most checks point down. The plan below shows where it starts, where it is proven wrong, and where it may go.", tone: "bear", icon: "▼" };
    case "HIGH-RISK SETUP":
      return {
        title: `Risky ${up ? "BUY" : "SELL"} setup`,
        text: "The direction is clear, but price is close to a big level, very jumpy, or just faked a breakout. Beginners should wait.",
        tone: "warn",
        icon: up ? "▲" : "▼",
      };
    case "LOW-QUALITY SETUP":
      return { title: "Weak setup: better to wait", text: `Leaning ${up ? "up" : "down"}, but the possible gain is small compared with the possible loss.`, tone: "warn", icon: "◆" };
    case "WATCH":
      return { title: `Watch: leaning ${up ? "up" : "down"}`, text: "Some checks point this way, but not enough for a setup yet.", tone: "info", icon: up ? "↗" : "↘" };
    default:
      return { title: "WAIT: no clear signal", text: "The checks don't agree, or some data is missing. Not trading is also a decision.", tone: "muted", icon: "■" };
  }
}

function strength(confidence: number): { label: string; tone: Tone } {
  if (confidence >= 55) return { label: "Strong", tone: "bull" };
  if (confidence >= 40) return { label: "Medium", tone: "warn" };
  return { label: "Weak", tone: "muted" };
}

function PlanRow({ label, value, topic, tone }: { label: string; value: string; topic: HelpTopic; tone?: Tone }) {
  return (
    <div className="flex items-center justify-between gap-2 border-t border-edge/60 py-1.5 first:border-t-0">
      <span className="flex items-center gap-1.5 text-xs text-muted">
        {label} <Help topic={topic} />
      </span>
      <span className={`font-mono text-sm ${tone ? TEXT_TONES[tone] : "text-text"}`}>{value}</span>
    </div>
  );
}

/** The beginner view of the engine's result: what it says, how sure, why, the plan and its track record. */
export default function SignalSummary({ snap }: { snap: Snapshot }) {
  const signal = snap.signal;
  const view = verdict(signal);
  const power = strength(signal.model_confidence);
  const quote = snap.quote && !isUnavailable(snap.quote) ? snap.quote : null;
  const plan = PLAN_LABELS.has(signal.label) ? signal.plan : null;
  const checks = signal.components.filter((c) => c.available && Math.abs(c.score) >= 0.15 && PHRASES[c.name]).sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
  const up = checks.filter((c) => c.score > 0).slice(0, 3);
  const down = checks.filter((c) => c.score < 0).slice(0, 3);
  const missing = signal.components.filter((c) => !c.available).map((c) => CHECK_NAMES[c.name] ?? c.name);

  return (
    <Card title={`Signal · ${snap.symbol}`} info={<Help topic="signal" />} actions={<span className="text-[11px] text-muted">{TIMEFRAME_LABELS[snap.timeframe] ?? snap.timeframe} candles</span>}>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-xs text-muted">{snap.meta.name}</div>
          <div className="font-mono text-2xl leading-tight">{num(snap.price)}</div>
        </div>
        {quote && quote.change_pct !== null && (
          <div className={`font-mono text-sm ${TEXT_TONES[toneForNumber(quote.change_pct)]}`}>
            {signed(quote.change)} ({pct(quote.change_pct)}) <span className="font-body text-xs text-muted">today</span>
          </div>
        )}
      </div>

      <div className={`mt-3 rounded-lg border p-3 ${BOX[view.tone]}`} role="status">
        <div className="flex items-center gap-2 font-display text-xl font-semibold">
          <span aria-hidden="true">{view.icon}</span>
          {view.title}
        </div>
        <p className="mt-1 text-xs leading-relaxed text-text">{view.text}</p>
      </div>

      <div className="mt-3">
        <div className="flex items-center justify-between text-xs">
          <span className="flex items-center gap-1.5 text-muted">
            Signal strength <Help topic="strength" />
          </span>
          <span className={TEXT_TONES[power.tone]}>
            {power.label} <span className="font-mono text-muted">({num(signal.model_confidence, 0)}/100)</span>
          </span>
        </div>
        <div className="mt-1">
          <Meter value={signal.model_confidence} tone={power.tone} />
        </div>
      </div>

      {plan && (
        <div className="mt-3 rounded-lg border border-edge bg-bg/40 px-3 py-1">
          <PlanRow label={plan.direction > 0 ? "Buy zone" : "Sell zone"} value={`${num(plan.entry_low)} – ${num(plan.entry_high)}`} topic="entry" tone="accent" />
          <PlanRow label="Stop loss" value={num(plan.stop)} topic="stop" tone="bear" />
          <PlanRow label="Target 1" value={num(plan.target1)} topic="target" tone="bull" />
          <PlanRow label="Target 2" value={num(plan.target2)} topic="target" tone="bull" />
          <PlanRow label="Reward vs risk" value={`1 : ${num(plan.risk_reward, 1)}`} topic="rr" />
        </div>
      )}

      <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2 xl:grid-cols-1">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-bull">▲ Pointing up</div>
          <ul className="mt-1 space-y-1">
            {up.length ? up.map((c) => <li key={c.name}>{PHRASES[c.name][0]}</li>) : <li className="text-muted">Nothing strong</li>}
          </ul>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wide text-bear">▼ Pointing down</div>
          <ul className="mt-1 space-y-1">
            {down.length ? down.map((c) => <li key={c.name}>{PHRASES[c.name][1]}</li>) : <li className="text-muted">Nothing strong</li>}
          </ul>
        </div>
      </div>
      {missing.length > 0 && <p className="mt-2 text-[11px] text-muted">No data for {missing.join(", ")} on this market, so those checks are skipped.</p>}

      <CalibrationNote symbol={snap.symbol} timeframe={snap.timeframe} bullish={signal.bullish_pct} direction={signal.direction} />

      <p className="mt-3 text-[11px] leading-snug text-muted">
        Based on the last finished candle ({istTime(signal.bar_time, { date: true })}). For learning and research, not investment advice. DalalSight never places real orders.
      </p>
    </Card>
  );
}
