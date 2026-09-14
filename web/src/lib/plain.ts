/** Plain-language names for engine output, shared by every beginner view. */
import type { Tone } from "./tones";
import { NO_TRADE } from "./types";

export interface Verdict {
  title: string;
  text: string;
  tone: Tone;
  icon: string;
}

function leaningUp(direction: number, bullish: number): boolean {
  return direction ? direction > 0 : bullish >= 50;
}

export function verdictFor(label: string, direction: number, bullish: number): Verdict {
  const up = leaningUp(direction, bullish);
  switch (label) {
    case "BULLISH SETUP":
      return { title: "BUY setup", text: "Most checks point up. The plan shows where it starts, where it is proven wrong, and where it may go.", tone: "bull", icon: "▲" };
    case "BEARISH SETUP":
      return { title: "SELL setup", text: "Most checks point down. The plan shows where it starts, where it is proven wrong, and where it may go.", tone: "bear", icon: "▼" };
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

/** Short label for tables and lists. */
export function plainLabel(label: string, direction = 0): string {
  switch (label) {
    case "BULLISH SETUP":
      return "BUY setup";
    case "BEARISH SETUP":
      return "SELL setup";
    case "HIGH-RISK SETUP":
      return direction > 0 ? "Risky BUY setup" : direction < 0 ? "Risky SELL setup" : "Risky setup";
    case "LOW-QUALITY SETUP":
      return "Weak setup";
    case "WATCH":
      return "Watch";
    case NO_TRADE:
      return "Wait";
    default:
      return label;
  }
}

export function strengthOf(confidence: number): { label: string; tone: Tone } {
  if (confidence >= 55) return { label: "Strong", tone: "bull" };
  if (confidence >= 40) return { label: "Medium", tone: "warn" };
  return { label: "Weak", tone: "muted" };
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

export function moodOf(code: string, direction: number): { title: string; text: string; tone: Tone } {
  const mood = MOODS[code];
  const title = code === "BREAKOUT" ? `Breakout ${direction > 0 ? "upward" : "downward"}` : (mood?.title ?? "");
  const tone: Tone = direction > 0 ? "bull" : direction < 0 ? "bear" : code === "HIGH_VOLATILITY" ? "warn" : "info";
  return { title, text: mood?.text ?? "", tone };
}

export const MOVE_SIZE: Record<string, string> = { high: "bigger than usual", normal: "normal", low: "smaller than usual", unknown: "not known yet" };
