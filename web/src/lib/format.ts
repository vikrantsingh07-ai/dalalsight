const formatters = new Map<number, Intl.NumberFormat>();

function formatter(digits: number): Intl.NumberFormat {
  let value = formatters.get(digits);
  if (!value) {
    value = new Intl.NumberFormat("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
    formatters.set(digits, value);
  }
  return value;
}

type Num = number | null | undefined;

const valid = (value: Num): value is number => value !== null && value !== undefined && Number.isFinite(value);

export function num(value: Num, digits = 2): string {
  return valid(value) ? formatter(digits).format(value) : "—";
}

export function signed(value: Num, digits = 2): string {
  return valid(value) ? `${value > 0 ? "+" : ""}${num(value, digits)}` : "—";
}

export function pct(value: Num, digits = 2): string {
  return valid(value) ? `${signed(value, digits)}%` : "—";
}

export function inr(value: Num, digits = 0): string {
  return valid(value) ? `₹${num(value, digits)}` : "—";
}

export function compact(value: Num): string {
  if (!valid(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e7) return `${num(value / 1e7, 2)} Cr`;
  if (abs >= 1e5) return `${num(value / 1e5, 2)} L`;
  if (abs >= 1e3) return `${num(value / 1e3, 1)} K`;
  return num(value, 0);
}

export function istTime(iso: string | null | undefined, options: { date?: boolean; seconds?: boolean } = {}): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    ...(options.seconds ? { second: "2-digit" } : {}),
    ...(options.date ? { day: "2-digit", month: "short" } : {}),
  });
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (!Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.max(seconds, 0)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

export function shortModel(model: string | null | undefined): string {
  if (!model) return "none";
  return model.split("/").pop() ?? model;
}

export function humanize(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
