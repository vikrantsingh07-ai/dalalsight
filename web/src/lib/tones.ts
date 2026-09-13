import { NO_TRADE } from "./types";

export type Tone = "bull" | "bear" | "warn" | "info" | "muted" | "accent";

export const TEXT_TONES: Record<Tone, string> = {
  bull: "text-bull",
  bear: "text-bear",
  warn: "text-warn",
  info: "text-info",
  muted: "text-muted",
  accent: "text-accent",
};

export function toneForStatus(status: string | null | undefined): Tone {
  switch (status) {
    case "ONLINE":
    case "completed":
      return "bull";
    case "DEGRADED":
    case "running":
      return "warn";
    case "ERROR":
    case "OFFLINE":
    case "failed":
      return "bear";
    default:
      return "muted";
  }
}

export function toneForLabel(label: string | null | undefined): Tone {
  if (!label) return "muted";
  if (label.startsWith("BULLISH")) return "bull";
  if (label.startsWith("BEARISH")) return "bear";
  if (label.startsWith("HIGH-RISK") || label.startsWith("LOW-QUALITY") || label === "UNPARSED") return "warn";
  if (label === "WATCH" || label.startsWith("MIXED")) return "info";
  if (label === "ERROR") return "bear";
  if (label === NO_TRADE || label === "NO_TRADE" || label === "NEUTRAL") return "muted";
  return "muted";
}

export function toneForPriority(priority: string): Tone {
  if (priority === "CRITICAL") return "bear";
  if (priority === "HIGH") return "warn";
  if (priority === "MEDIUM") return "info";
  return "muted";
}

export function toneForNumber(value: number | null | undefined): Tone {
  if (value === null || value === undefined || value === 0) return "muted";
  return value > 0 ? "bull" : "bear";
}
